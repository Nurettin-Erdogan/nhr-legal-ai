"""Büro AI akışları: dilekçe/sözleşme üretimi, belge analizi, risk analizi, özet ve OCR.

Üretim yerel modelle (`create_provider`, varsayılan DeepSeek/Ollama) yapılır; buluta gitmez.
Hukuki dayanak kuralı bu akışlarda da geçerlidir ve **kodda** denetlenir:

* Modele yalnız korpustan getirilen kaynaklar `[K1]`, `[K2]` işaretleriyle verilir; prompt, hukuki
  atıfın yalnız bu kaynaklardan yapılmasını ister.
* Ortak kaynak destek denetimini geçmeyen çıktı gösterilmez/kaydedilmez (HTTP 422).
* Üçüncü taraf (`third_party`) kaynaklar üretim bağlamına alınmaz.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import shutil
from typing import Annotated, Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api import case_summary, deep_research, draft_documents, office_analysis
from api.ai.pipeline import _embed_question, _generation_lock, _retrieve
from api.ai.providers import AIProviderError, create_provider
from api.ai.rag import RAGContext
from api.ai.verification import verify_answer
from api.auth.routes import current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection
from api.schemas import AIAnswerRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office-ai", tags=["office-ai"])

_MAX_USER_CHARS = 3200
_SOURCE_CHARS = 600
_SOURCE_COUNT = 3
_MAX_OUTPUT_TOKENS = 800
# Yerel model yavaştır; belge üretimi sohbet cevabından uzundur.
_GENERATION_TIMEOUT_SECONDS = 540.0

_RULES = (
    "KURALLAR:\n"
    "- Türkçe yaz.\n"
    "- Kanun maddesi, karar veya içtihat YALNIZCA aşağıdaki KAYNAKLAR bölümünden ve [K1], [K2] işaretiyle "
    "anılabilir. Kaynaklarda yoksa hukuki dayanağı kendin ekleme; 'kaynak bulunamadı' de.\n"
    "- Kaynak bölümünde 'UYARI' satırı olan kaynak doğrulanmamıştır; kesin dille sunma.\n"
    "- Yerel model sınırlı olduğundan yanıtı en çok 300 kelimeyle sınırla; gerekirse bölümleri kısa tut.\n"
    "- Kullanıcı metninde olmayan bilgiyi (isim, tarih, tutar, dosya no) uydurma; eksikleri […] ile bırak.\n"
)

MODULE_PROMPTS: dict[str, tuple[str, str]] = {
    "document_analysis": (
        "Belge Analizi",
        "Sen hukuki belge analizi yapan bir avukat asistanısın. Verilen belgeyi incele ve şu başlıklarla "
        "Markdown rapor yaz: Belge Türü ve Özeti, Taraflar, Anahtar Hükümler, Riskli veya Eksik Noktalar, "
        "Önerilen Adımlar.\n" + _RULES,
    ),
    "auto_summary": (
        "Özet",
        "Sen hukuki belgeleri özetleyen bir avukat asistanısın. Verilen belge(ler)i kısa ve maddeler hâlinde "
        "özetle; birden fazla belge varsa ortak ve farklı noktaları ayrı başlıkta göster.\n" + _RULES,
    ),
    "risk_analysis": (
        "Risk Analizi",
        "Sen hukuki risk analizi yapan bir avukat asistanısın. Olayı/belgeyi değerlendir ve şu başlıklarla "
        "Markdown rapor yaz: Özet, Güçlü Yönler, Riskler (yüksek/orta/düşük), Önerilen Adımlar. Dava sonucu "
        "için kesin tahmin verme; yalnızca gerekçeli bir değerlendirme yap.\n" + _RULES,
    ),
    "contract_draft": (
        "Sözleşme Taslağı",
        "Sen sözleşme hazırlayan bir avukat asistanısın. Talebe uygun, maddeler hâlinde bir sözleşme taslağı "
        "yaz (taraflar, konu, bedel/ödeme, süre, sona erme, uyuşmazlık çözümü).\n" + _RULES,
    ),
    "draft": (
        "Dilekçe Taslağı",
        "Sen dilekçe hazırlayan bir avukat asistanısın. Başlık, taraflar, KONU, AÇIKLAMALAR (numaralı), "
        "HUKUKİ NEDENLER, DELİLLER, SONUÇ VE İSTEM, tarih/imza yapısıyla resmî üslupta bir taslak yaz.\n"
        + _RULES,
    ),
}

DOCUMENT_TYPES = {
    "dilekce": "Dava Dilekçesi",
    "sozlesme": "Sözleşme",
    "ihtarname": "İhtarname",
    "diger": "Hukuki Belge",
}
PETITION_TYPES = {
    "itiraz": "İtiraz Dilekçesi",
    "temyiz": "Temyiz Dilekçesi",
    "istinaf": "İstinaf Başvuru Dilekçesi",
    "cevap": "Cevap Dilekçesi",
    "dava": "Dava Dilekçesi",
    "beyan": "Beyan Dilekçesi",
    "talep": "Talep Dilekçesi",
}

_LAW_NO = re.compile(r"\b(\d{3,5})\s+sayılı", re.IGNORECASE)
_DECISION_NO = re.compile(r"\b((?:19|20)\d{2}/\d{1,6})\b")


def _blob(context: RAGContext) -> str:
    return " ".join(
        part
        for part in (
            context.reference_line,
            context.law_no,
            context.docket_no,
            context.decision_no,
            context.content,
        )
        if part
    )


def unsupported_references(text: str, contexts: list[RAGContext], *, given_text: str = "") -> list[str]:
    """Çıktıdaki kanun/karar numaralarından, kaynaklarda ya da kullanıcı metninde geçmeyenleri döndürür."""
    haystack = " ".join([*(_blob(c) for c in contexts), given_text])
    missing: list[str] = []
    for match in _LAW_NO.finditer(text):
        value = f"{match.group(1)} sayılı"
        if match.group(1) not in haystack and value not in missing:
            missing.append(value)
    for match in _DECISION_NO.finditer(text):
        value = match.group(1)
        if value not in haystack and value not in missing:
            missing.append(value)
    return missing


def _sources_block(contexts: list[RAGContext]) -> str:
    if not contexts:
        return "KAYNAKLAR:\n(Korpusta ilgili kaynak bulunamadı.)"
    blocks = []
    for index, context in enumerate(contexts, start=1):
        lines = [f"[K{index}] {context.reference_line}"]
        if context.verification == "third_party":
            lines.append("UYARI: Üçüncü taraf arşivden; resmî portalla henüz doğrulanmadı.")
        lines.append(context.content[:_SOURCE_CHARS])
        blocks.append("\n".join(lines))
    return "KAYNAKLAR:\n" + "\n\n".join(blocks)


def _sources_footer(contexts: list[RAGContext]) -> str:
    if not contexts:
        return ""
    lines = []
    for index, context in enumerate(contexts, start=1):
        # Etiket kuralı: resmî metinle karşılaştırılmış kayıt "Resmî metin ✓"; karşılaştırılmamış kayıt olumsuz ibare de ✓ de almaz.
        badge = " (Resmî metin ✓)" if context.verification == "official" else ""
        lines.append(f"- [K{index}] {context.reference_line}{badge}")
    return "\n\n**Kaynaklar**\n" + "\n".join(lines)


def _sources_payload(contexts: list[RAGContext]) -> list[dict[str, Any]]:
    return [
        {
            "marker": f"K{index}",
            "reference": context.reference_line,
            "source_url": context.source_url,
            "verification": context.verification,
        }
        for index, context in enumerate(contexts, start=1)
    ]


async def _retrieve_sources(query: str, user_id: UUID, top_k: int = _SOURCE_COUNT) -> list[RAGContext]:
    settings = get_settings()
    question = query.strip()[:1900]
    if len(question) < 5:
        return []
    request = AIAnswerRequest(question=question)
    try:
        embedding = await _embed_question(question) if settings.rag_query_embedding else None
        return await asyncio.to_thread(
            _retrieve,
            request,
            user_id=user_id,
            query_embedding=embedding,
            top_k=top_k,
            embedding_model=settings.embedding_model,
        )
    except Exception:  # noqa: BLE001 - kaynak bulunamasa da üretim kaynaksız-uyarıyla sürer
        logger.exception("Büro AI kaynak araması başarısız")
        return []


async def _generate(system: str, prompt: str) -> tuple[str, str]:
    """Yerel sağlayıcıyla üretir; (metin, model adı) döndürür."""
    settings = get_settings()
    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=max(settings.ollama_timeout_seconds, _GENERATION_TIMEOUT_SECONDS),
            ollama_max_output_tokens=max(settings.ollama_max_output_tokens, _MAX_OUTPUT_TOKENS),
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_keep_alive=settings.ollama_keep_alive,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        async with _generation_lock:
            text = await asyncio.to_thread(
                provider.generate, system_instruction=system, prompt=prompt
            )
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return text.strip(), provider.model


def _document_context(user_id: UUID, doc_ids: list[UUID], budget: int) -> str:
    if not doc_ids:
        return ""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            # Sunucuda çıkarılan (indekslenmiş) metin varsa o kullanılır; `content_excerpt` yalnız bazı yükleme yollarında dolar ve
            # elle yüklenen belgeler "metin çıkarılamadı" diye boş gidiyordu (ölçüldü: 2026-10-05).
            rows = connection.execute(
                "SELECT od.file_name, od.uyap_file_no, od.uyap_birim, od.doc_date, "
                "  COALESCE((SELECT string_agg(part.content, E'\\n\\n' ORDER BY part.chunk_index) FROM ("
                "      SELECT c.content, c.chunk_index FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                "      WHERE d.office_case_document_id = od.id AND d.status = 'ready' ORDER BY c.chunk_index LIMIT 4) part), "
                "    od.content_excerpt) AS content_excerpt "
                "FROM office_case_documents od WHERE od.id = ANY(%s::uuid[]) AND od.deleted_at IS NULL LIMIT 40",
                (doc_ids,),
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("Dosya belgeleri okunamadı")
        raise HTTPException(status_code=503, detail="Dosya belgeleri okunamadı") from exc
    if not rows:
        return ""
    per_doc = max(600, budget // len(rows))
    parts = []
    for row in rows:
        meta = " • ".join(str(v) for v in (row["uyap_file_no"], row["uyap_birim"], row["doc_date"]) if v)
        excerpt = (row["content_excerpt"] or "(metin çıkarılamadı)")[:per_doc]
        parts.append(f"### {row['file_name']}\n{meta}\n{excerpt}".strip())
    return "\n\nDOSYA BELGELERİ:\n" + "\n\n".join(parts)


def _statute_hints(text: str) -> list[dict]:
    """Konu ipuçlarından korpusta resmî doğrulanmış maddeler; veritabanı yoksa ya da eşleşme yoksa boş liste."""
    from api import statute_hints
    from api.db import database_connection

    hints = statute_hints.suggest(text)
    if not hints:
        return []
    try:
        with database_connection() as connection:
            return statute_hints.load_verified(connection, hints)
    except psycopg.Error:
        logger.warning("Madde ipuçları yüklenemedi", exc_info=True)
        return []


async def _statute_hints_async(text: str) -> list[dict]:
    return await asyncio.to_thread(_statute_hints, text)


async def _condense_topic(narrative: str) -> str | None:
    """Olay anlatımını araştırma konusuna indirger; model çıktısı kodla denetlenir (deep_research.accept_topic)."""
    import json

    try:
        raw, _model = await _generate(deep_research.CONDENSE_SYSTEM, narrative[:1500])
        data = json.loads(raw[7:-3].strip() if raw.startswith("```json") and raw.endswith("```") else raw)
    except (HTTPException, ValueError, TypeError):
        return None
    return deep_research.accept_topic(data.get("topic") if isinstance(data, dict) else None, narrative)


class RunRequest(BaseModel):
    module: str
    prompt: str = Field(min_length=5, max_length=20000)
    title: str | None = Field(default=None, max_length=200)
    doc_ids: list[UUID] = Field(default_factory=list, max_length=40)
    case_id: UUID | None = None
    project_id: UUID | None = None


async def _draft(
    doc_type: str,
    title: str | None,
    parties: list[str],
    subject: str,
    details: str | None,
    user_id: UUID,
    *,
    extra: str = "",
) -> dict[str, Any]:
    """Taslak: kodla kurulan iskelet + doğrulanmış olay anlatımı + kodla listelenen resmî dayanaklar (api.draft_documents)."""
    label = draft_documents.DOC_LABELS.get(doc_type, draft_documents.DOC_LABELS["diger"])
    given = draft_documents.given_text(parties, subject, details, extra)
    topic = f"{subject} {(details or '')[:300]}"
    contexts = await _retrieve_sources(topic, user_id, top_k=12)
    suggested = await asyncio.to_thread(_statute_hints, f"{subject} {(details or '')[:1500]}")
    legal = draft_documents.legal_references(contexts, question=topic, suggested=suggested)
    model = None
    paragraphs: list[str] = []
    prompt = (
        f"Belge türü: {label}\nTaraflar: {'; '.join(parties) or '(belirtilmedi)'}\nKonu: {subject}\n"
        f"Olgular: {(details or '(yok)')[:1500]}{extra[:1200]}\n\nOlguları numaralı paragraflar hâlinde yaz."
    )
    if draft_documents.has_facts(details, extra):
        try:
            output, model = await _generate(draft_documents.FACT_SYSTEM, prompt)
            grouped = draft_documents.verified_paragraphs(output, given)

            async def check(system: str, text: str) -> str:
                return (await _generate(system, text))[0]

            # Kod denetimi koşulun/olumsuzluğun ters çevrilmesini göremez; cümleler bir de modele denetletilir (yalnız eler).
            flat = [sentence for sentences in grouped for sentence in sentences]
            approved, _rejected = await case_summary.check_bullets(flat, [given[:6000]], check)
            allowed = set(approved)
            paragraphs = draft_documents.join_paragraphs([[s for s in sentences if s in allowed] for sentences in grouped])
        except HTTPException:
            logger.warning("Taslak olay anlatımı modelden alınamadı; kullanıcının olguları kullanılacak")
    from_user = not paragraphs
    if from_user:
        paragraphs = draft_documents.fallback_paragraphs(subject, details or extra[:600])
    content = draft_documents.build_document(doc_type, title, parties, subject, paragraphs, legal)
    if from_user and draft_documents.has_facts(details, extra):
        content += "_Olay anlatımı model çıktısı doğrulanamadığı ya da alınamadığı için sizin yazdığınız bilgilerle oluşturuldu; üslubu düzeltin._\n"
    elif from_user:
        content += "_Olgu verilmediği için açıklamalar bölümü boş bırakıldı: olayları, tarihleri ve tutarları yazıp yeniden oluşturun ya da elle doldurun._\n"
    return {"content": content, "model": model, "sources": legal.sources, "unverified_references": [], "label": label}


async def _risk(prompt: str, user_id: UUID) -> dict[str, Any]:
    """Risk analizi: dava sonucu tahmini yapılmaz; olay mevzuat / yargı kararları / süre-ispat başlıklarında kaynaklı incelenir."""
    job = deep_research.ResearchJob(id=uuid4(), owner_id=user_id, question=prompt.strip()[: deep_research.MAX_QUESTION_CHARS])
    await deep_research.run_job(
        job, lambda question, conversation_id: _deep_answer(user_id, question, conversation_id),
        condense=_condense_topic, statute_hints=_statute_hints_async,
    )
    if job.state != "done":
        raise HTTPException(status_code=502, detail=job.error or "Kaynaklı inceleme tamamlanamadı")
    markdown = deep_research.render_markdown(job.question, job.steps, topic=job.topic, hints=job.hints).replace(
        "# Derin araştırma raporu", "# Risk analizi: kaynaklı inceleme\n\n_Dava sonucu tahmini yapılmaz; aşağıda olay üç başlıkta kaynaklara göre incelenmiştir._", 1
    )
    sources = [{"reference": c["reference"], "source_url": c.get("source_url"), "verification": c.get("verification")} for step in job.steps for c in step.citations]
    return {"content": markdown, "model": None, "sources": sources, "unverified_references": [], "label": "Risk Analizi"}


def _selected_analysis_documents(user_id: UUID, ids: list[UUID]) -> list[tuple[str, str]]:
    """Seçili belgeler ayrı kaynaklardır; kısa künye örnekleri tam metin yerine kullanılmaz."""
    wanted = list(dict.fromkeys(ids))
    if len(wanted) > office_analysis.MAX_DOCUMENTS:
        raise HTTPException(status_code=422, detail="Bir analiz için en fazla 4 belge seçilebilir. Daha büyük dosyalar için dava içindeki Dosya Özeti'ni kullanın.")
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                "SELECT od.id, od.file_name, "
                " (SELECT string_agg(c.content, E'\\n\\n' ORDER BY c.chunk_index) "
                "  FROM document_chunks c WHERE c.document_id = d.id) AS text "
                "FROM office_case_documents od JOIN documents d ON d.office_case_document_id = od.id "
                "WHERE od.id = ANY(%s::uuid[]) AND od.deleted_at IS NULL AND d.status = 'ready' "
                "ORDER BY array_position(%s::uuid[], od.id)", (wanted, wanted),
            ).fetchall()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Seçili belgelerin metni okunamadı.") from exc
    if len(rows) != len(wanted) or any(not (row["text"] or "").strip() for row in rows):
        # Olmayan/yetkisiz/henüz indekslenmemiş belge ayrımı dışarıya açılmaz.
        raise HTTPException(status_code=409, detail="Seçili belgelerin tamamı okunabilir değil. Belge listesini yenileyip metin işleme durumunu kontrol edin.")
    return [(row["file_name"], row["text"]) for row in rows]


async def _analysis(prompt: str, user_id: UUID, title: str, documents: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    async def generate(system: str, text: str) -> str:
        output, _ = await _generate(system, text)
        return output

    query = "\n".join(text[:600] for _, text in documents) if documents else prompt[:600]
    contexts = await _retrieve_sources(query[:1900], user_id, top_k=6)
    markdown, sources = await office_analysis.analyze(prompt, generate, contexts, title=title, documents=documents)
    return {"content": markdown, "model": None, "sources": sources, "unverified_references": [], "label": title}


def _first_sentence(text: str, limit: int = 200) -> str:
    clean = " ".join(text.split())
    cut = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)[0]
    return cut[:limit].strip() or clean[:limit]


@router.post("/run")
async def run_module(
    body: RunRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    if body.module not in MODULE_PROMPTS:
        raise HTTPException(status_code=400, detail="Bu modül yerel AI hattında desteklenmiyor")
    label = MODULE_PROMPTS[body.module][0]
    is_analysis = body.module in ("document_analysis", "auto_summary")
    selected = await asyncio.to_thread(_selected_analysis_documents, user_id, body.doc_ids) if is_analysis and body.doc_ids else None
    docs = "" if is_analysis else await asyncio.to_thread(_document_context, user_id, body.doc_ids, _MAX_USER_CHARS)
    prompt = body.prompt.strip()
    if body.module in ("draft", "contract_draft"):
        result = await _draft(
            "sozlesme" if body.module == "contract_draft" else "dilekce", body.title, [], _first_sentence(prompt), prompt, user_id, extra=docs
        )
    elif body.module == "risk_analysis":
        result = await _risk(f"{prompt}\n{docs}".strip(), user_id)
        if body.doc_ids:
            result["content"] += "\n\n_Belge kapsamı: bu inceleme seçili belgelerin kısa metin örnekleriyle hazırlanmıştır; belgelerin tamamının incelendiği anlamına gelmez._\n"
    else:  # document_analysis, auto_summary
        result = await _analysis(prompt, user_id, "Belge analizi" if body.module == "document_analysis" else "Toplu özet", selected)
    title = (body.title or "").strip() or f"{label}: {prompt[:60]}"
    output_id = uuid4()
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            connection.execute(
                "INSERT INTO office_ai_outputs (id, owner_id, module, title, prompt, output, sources, model, "
                "case_id, project_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    output_id,
                    user_id,
                    body.module,
                    title,
                    body.prompt[:20000],
                    result["content"],
                    Jsonb(result["sources"]),
                    result["model"],
                    body.case_id,
                    body.project_id,
                ),
            )
    except psycopg.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=409, detail="İlişkili kayıt bulunamadı") from exc
    except psycopg.Error as exc:
        logger.exception("AI çıktısı kaydedilemedi")
        raise HTTPException(status_code=503, detail="AI çıktısı kaydedilemedi") from exc
    return {
        "id": str(output_id),
        "title": title,
        "output": result["content"],
        "model": result["model"],
        "sources": result["sources"],
        "unverified_references": result["unverified_references"],
    }


class DocumentRequest(BaseModel):
    doc_type: str = Field(max_length=40)
    title: str | None = Field(default=None, max_length=200)
    parties: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(min_length=3, max_length=2000)
    details: str | None = Field(default=None, max_length=8000)
    doc_ids: list[UUID] = Field(default_factory=list, max_length=40)


@router.post("/document")
async def generate_document(
    body: DocumentRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    docs = await asyncio.to_thread(_document_context, user_id, body.doc_ids, _MAX_USER_CHARS // 2)
    result = await _draft(body.doc_type, body.title, [party for party in body.parties if party.strip()], body.subject.strip(), body.details, user_id, extra=docs)
    return {"content": result["content"], "model": result["model"], "sources": result["sources"], "unverified_references": result["unverified_references"]}


class PetitionRequest(BaseModel):
    text: str = Field(min_length=100, max_length=200000)
    petition_type: str = Field(max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    file_name: str | None = Field(default=None, max_length=240)


@router.post("/petition")
async def petition_from_text(
    body: PetitionRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    label = PETITION_TYPES.get(body.petition_type, "Dilekçe")
    result = await _draft("dilekce", label, [], label, body.text[:2400], user_id, extra=(body.notes or "")[:500])
    return {"content": result["content"], "label": label, "sources": result["sources"]}


class OcrRequest(BaseModel):
    images: list[str] = Field(min_length=1, max_length=12)


def _ocr_available() -> tuple[bool, str]:
    # Ortak OCR motoru (Tesseract'ı PATH dışında da bulur, Türkçe dil paketini şart koşar).
    from api.ocr import ocr_status

    return ocr_status()


def _ocr_pages(images: list[str]) -> list[str]:
    from api.ocr import OcrTooLarge, OcrUnavailable, ocr_image_pages

    pages: list[str] = []
    for image in images:
        raw = image.split(",", 1)[1] if image.startswith("data:") and "," in image else image
        try:
            data = base64.b64decode(raw, validate=False)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Görsel okunamadı") from exc
        try:
            pages.extend(text for _, text in ocr_image_pages(data))
        except (OcrUnavailable, OcrTooLarge) as exc:
            raise HTTPException(status_code=400, detail=f"Görsel okunamadı: {exc}") from exc
    return pages


@router.post("/ocr")
async def ocr_images(
    body: OcrRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    ok, reason = _ocr_available()
    if not ok:
        raise HTTPException(status_code=503, detail=reason)
    pages = await asyncio.to_thread(_ocr_pages, body.images)
    return {"text": "\n\n--- sayfa ---\n\n".join(pages), "pages": len(pages)}


# --- Dosya özeti: davaya bağlı belgelerin toplu özeti (arka plan işi) -----------------------------------------------------
# Yerel model belge başına dakikalar harcayabilir; bu yüzden iş arka planda yürür, arayüz ilerlemeyi yoklar. Model çıktısı kodda
# belgeyle doğrulanır (api.case_summary.verify_summary); belgede olmayan rakam/numara ya da zayıf dayanaklı madde gösterilmez.

_SUMMARY_MODULE = "case_summary"


class CaseSummaryRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=case_summary.MAX_DOCUMENTS)


def _load_case_documents(user_id: UUID, case_id: UUID, ids: list[UUID]) -> list[dict]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            if connection.execute("SELECT id FROM office_cases WHERE id = %s", (case_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="Dava bulunamadı veya erişim yetkiniz yok")
            return case_summary.load_ready_documents(connection, case_id, list(dict.fromkeys(ids)))
    except psycopg.Error as exc:
        logger.exception("Dosya özeti belgeleri okunamadı")
        raise HTTPException(status_code=503, detail="Dava belgeleri okunamadı") from exc


def _save_case_summary(job: case_summary.SummaryJob, models: set[str]) -> UUID:
    from api.audit import AuditContext, record_event

    output_id = uuid4()
    payload = [{"marker": f"B{index}", "verification": "user_document", **result.as_dict()} for index, result in enumerate(job.results, 1)]
    with authenticated_database_connection(str(job.owner_id)) as connection:
        connection.execute(
            "INSERT INTO office_ai_outputs (id, owner_id, module, title, prompt, output, sources, model, case_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                output_id, job.owner_id, _SUMMARY_MODULE, f"Dosya özeti ({len(job.results)} belge)",
                f"Dosya özeti: {len(job.results)} belge", case_summary.render_markdown(job.results), Jsonb(payload),
                ", ".join(sorted(models))[:200] or None, job.case_id,
            ),
        )
        record_event(connection, action="office.case_summary", actor_user_id=job.owner_id, context=AuditContext(uuid4()),
                     entity_type="office_ai_outputs", entity_id=output_id,
                     metadata={"case_id": str(job.case_id), "documents": len(job.results)})
    return output_id


async def _run_summary_job(job: case_summary.SummaryJob, documents: list[dict]) -> None:
    models: set[str] = set()

    async def generate(system: str, prompt: str) -> str:
        text, model = await _generate(system, prompt)
        models.add(model)
        return text

    try:
        for document in documents:
            try:
                result = await case_summary.summarize_document(
                    document["id"], document["file_name"], document["text"], ocr=document["ocr"], generate=generate
                )
            except HTTPException as exc:
                result = case_summary.DocumentSummary(document["id"], document["file_name"], ocr=document["ocr"], error=str(exc.detail))
            except Exception:  # noqa: BLE001 - bir belgenin hatası diğerlerini durdurmaz
                logger.exception("Belge özeti üretilemedi")
                result = case_summary.DocumentSummary(document["id"], document["file_name"], ocr=document["ocr"], error="Özet üretilemedi.")
            job.results.append(result)
            job.done += 1
        if any(result.bullets for result in job.results):
            try:
                job.saved_id = await asyncio.to_thread(_save_case_summary, job, models)
            except Exception:  # noqa: BLE001 - kayıt başarısızsa sonuç bu oturumda yine görünür
                logger.exception("Dosya özeti kaydedilemedi")
            job.state = "done"
        else:
            job.state = "failed"
            job.error = "Hiçbir belge için doğrulanmış özet üretilemedi."
    except Exception:  # noqa: BLE001
        logger.exception("Dosya özeti işi çöktü")
        job.state = "failed"
        job.error = "Özet işi beklenmedik biçimde durdu."


@router.post("/cases/{case_id}/summary", status_code=202)
async def start_case_summary(
    case_id: UUID, body: CaseSummaryRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    if case_summary.registry.running_for(user_id) is not None:
        raise HTTPException(status_code=409, detail="Devam eden bir özet işiniz var; bitmesini bekleyin.")
    wanted = list(dict.fromkeys(body.document_ids))
    documents = await asyncio.to_thread(_load_case_documents, user_id, case_id, wanted)
    if len(documents) != len(wanted):
        raise HTTPException(
            status_code=409, detail="Seçilen belgelerden bazıları bu davada yok ya da henüz okunmuş (aranabilir) değil."
        )
    if case_summary.registry.running_for(user_id) is not None:  # yükleme sırasında başka istek iş açmış olabilir
        raise HTTPException(status_code=409, detail="Devam eden bir özet işiniz var; bitmesini bekleyin.")
    job = case_summary.SummaryJob(id=uuid4(), owner_id=user_id, case_id=case_id, total=len(documents))
    case_summary.registry.add(job, _run_summary_job(job, documents))
    return {"job_id": str(job.id), "total": job.total}


@router.get("/cases/{case_id}/summary")
def get_case_summary(case_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Sürmekte olan/son iş ve kaydedilmiş son dosya özeti. Başkasının davası boş döner (RLS)."""
    job = case_summary.registry.latest_for(user_id, case_id)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            row = connection.execute(
                "SELECT id, created_at, output, sources, model FROM office_ai_outputs "
                "WHERE case_id = %s AND module = %s ORDER BY created_at DESC LIMIT 1",
                (case_id, _SUMMARY_MODULE),
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("Dosya özeti okunamadı")
        raise HTTPException(status_code=503, detail="Dosya özeti okunamadı") from exc
    latest = (
        {"id": str(row["id"]), "created_at": row["created_at"].isoformat(), "documents": row["sources"] or [],
         "markdown": row["output"], "model": row["model"]}
        if row else None
    )
    return {"job": job.as_dict() if job else None, "latest": latest}


# --- Derin araştırma: sabit eksenlerle çok adımlı, kodda doğrulanan rapor (api.deep_research) ------------------------------
_DEEP_MODULE = "deep_research"


class DeepResearchRequest(BaseModel):
    question: str = Field(min_length=deep_research.MIN_QUESTION_CHARS, max_length=deep_research.MAX_QUESTION_CHARS)


async def _deep_answer(user_id: UUID, question: str, conversation_id: UUID | None):
    # Adımlar tek sohbette toplanır (ilk adım sohbeti açar); her cevap kendi atıf doğrulamasından geçer.
    from api.ai.pipeline import execute_answer

    response, _timings = await execute_answer(AIAnswerRequest(question=question, conversation_id=conversation_id), user_id)
    return response


def _save_deep_research(job: deep_research.ResearchJob) -> UUID:
    from api.audit import AuditContext, record_event

    output_id = uuid4()
    steps = [step.as_dict() for step in job.steps]
    with authenticated_database_connection(str(job.owner_id)) as connection:
        connection.execute(
            "INSERT INTO office_ai_outputs (id, owner_id, module, title, prompt, output, sources) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                output_id, job.owner_id, _DEEP_MODULE, f"Derin araştırma: {' '.join(job.question.split())[:60]}", job.question[:20000],
                deep_research.render_markdown(job.question, job.steps, topic=job.topic, hints=job.hints),
                Jsonb({"steps": steps, "topic": job.topic, "hints": [{"reference": h["reference"], "source_url": h.get("source_url")} for h in job.hints]}),
            ),
        )
        record_event(connection, action="office.deep_research", actor_user_id=job.owner_id, context=AuditContext(uuid4()),
                     entity_type="office_ai_outputs", entity_id=output_id,
                     metadata={"steps": len(steps), "grounded": sum(1 for step in steps if step["grounded"])})
    return output_id


async def _deep_run(job: deep_research.ResearchJob) -> None:
    async def save(finished: deep_research.ResearchJob) -> None:
        finished.saved_id = await asyncio.to_thread(_save_deep_research, finished)

    await deep_research.run_job(
        job, lambda question, conversation_id: _deep_answer(job.owner_id, question, conversation_id), on_done=save,
        condense=_condense_topic, statute_hints=_statute_hints_async,
    )


@router.post("/deep-research", status_code=202)
async def start_deep_research(body: DeepResearchRequest, user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    if deep_research.registry.running_for(user_id) is not None:
        raise HTTPException(status_code=409, detail="Devam eden bir araştırmanız var; bitmesini bekleyin.")
    job = deep_research.ResearchJob(id=uuid4(), owner_id=user_id, question=body.question.strip())
    deep_research.registry.add(job, _deep_run(job))
    return {"job_id": str(job.id), "steps": [axis.title for axis in deep_research.AXES]}


@router.get("/deep-research")
def get_deep_research(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Sürmekte olan/son iş ve kaydedilmiş son rapor (yalnız kendi kayıtları: RLS)."""
    job = deep_research.registry.latest_for(user_id)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            row = connection.execute(
                "SELECT id, created_at, prompt, output, sources FROM office_ai_outputs WHERE module = %s ORDER BY created_at DESC LIMIT 1",
                (_DEEP_MODULE,),
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("Derin araştırma raporu okunamadı")
        raise HTTPException(status_code=503, detail="Rapor okunamadı") from exc
    latest = (
        {"id": str(row["id"]), "created_at": row["created_at"].isoformat(), "question": row["prompt"], "markdown": row["output"],
         "steps": (row["sources"] or {}).get("steps", []) if isinstance(row["sources"], dict) else []}
        if row else None
    )
    return {"job": job.as_dict() if job else None, "latest": latest}


@router.get("/status")
def office_ai_status(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    ok, reason = _ocr_available()
    return {"ocr": ok, "ocr_detail": reason or None, "modules": sorted(MODULE_PROMPTS)}
