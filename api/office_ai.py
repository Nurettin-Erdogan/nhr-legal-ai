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
        badge = " (doğrulanmadı)" if context.verification == "third_party" else ""
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


async def _retrieve_sources(query: str, user_id: UUID) -> list[RAGContext]:
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
            top_k=_SOURCE_COUNT,
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
            rows = connection.execute(
                "SELECT file_name, uyap_file_no, uyap_birim, doc_date, content_excerpt "
                "FROM office_case_documents WHERE id = ANY(%s::uuid[]) AND deleted_at IS NULL LIMIT 40",
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


class RunRequest(BaseModel):
    module: str
    prompt: str = Field(min_length=5, max_length=20000)
    title: str | None = Field(default=None, max_length=200)
    doc_ids: list[UUID] = Field(default_factory=list, max_length=40)
    case_id: UUID | None = None
    project_id: UUID | None = None


async def _run_module(
    label: str, system: str, user_text: str, user_id: UUID, *, retrieval_query: str
) -> dict[str, Any]:
    contexts = await _retrieve_sources(retrieval_query, user_id)
    # An auxiliary module must not bypass the assistant's evidence gate.
    contexts = [context for context in contexts if context.verification == "official"]
    if not contexts:
        raise HTTPException(status_code=422, detail="İlgili doğrulanmış kaynak bulunamadı; hukuki belge üretilmedi.")
    prompt = f"{user_text[:_MAX_USER_CHARS]}\n\n{_sources_block(contexts)}"
    text, model = await _generate(system, prompt)
    if not text:
        raise HTTPException(status_code=502, detail="Model boş cevap döndürdü")
    missing = unsupported_references(text, contexts, given_text=user_text)
    verified = verify_answer(text, contexts, question=retrieval_query)
    if missing or not verified.grounded:
        raise HTTPException(status_code=422, detail="Üretilen metin getirilen kaynaklarla desteklenemedi; çıktı gösterilmedi veya kaydedilmedi.")
    contexts = list(verified.contexts)
    output = verified.text + _sources_footer(contexts)
    return {
        "content": output,
        "model": model,
        "sources": _sources_payload(contexts),
        "unverified_references": missing,
        "label": label,
    }


@router.post("/run")
async def run_module(
    body: RunRequest, user_id: Annotated[UUID, Depends(current_user_id)]
) -> dict[str, Any]:
    if body.module not in MODULE_PROMPTS:
        raise HTTPException(status_code=400, detail="Bu modül yerel AI hattında desteklenmiyor")
    label, system = MODULE_PROMPTS[body.module]
    docs = await asyncio.to_thread(_document_context, user_id, body.doc_ids, _MAX_USER_CHARS // 2)
    user_text = f"{body.prompt.strip()[: _MAX_USER_CHARS // 2 if docs else _MAX_USER_CHARS]}{docs}"
    result = await _run_module(label, system, user_text, user_id, retrieval_query=body.prompt)
    title = (body.title or "").strip() or f"{label}: {body.prompt.strip()[:60]}"
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
    label = DOCUMENT_TYPES.get(body.doc_type, body.doc_type)
    module = "contract_draft" if body.doc_type == "sozlesme" else "draft"
    system = MODULE_PROMPTS[module][1]
    docs = await asyncio.to_thread(_document_context, user_id, body.doc_ids, _MAX_USER_CHARS // 2)
    user_text = (
        f"Belge Türü: {label}\nBaşlık: {body.title or '(otomatik üret)'}\n"
        f"Taraflar: {'; '.join(body.parties) or '(belirtilmedi)'}\nKonu: {body.subject}\n"
        f"Ek Detaylar: {(body.details or '(yok)')[:1500]}{docs}\n\n"
        f"Yukarıdaki bilgilere göre eksiksiz bir {label} hazırla; olmayan bilgi için […] bırak."
    )
    result = await _run_module(label, system, user_text, user_id, retrieval_query=body.subject)
    return {
        "content": result["content"],
        "model": result["model"],
        "sources": result["sources"],
        "unverified_references": result["unverified_references"],
    }


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
    system = MODULE_PROMPTS["draft"][1]
    user_text = (
        f"Belge Türü: {label}\nKaynak Belge Adı: {body.file_name or '(belirtilmedi)'}\n"
        f"Kullanıcı Notu: {(body.notes or '(yok)')[:500]}\n\n"
        f'KAYNAK BELGE METNİ (gerçek veri):\n"""\n{body.text[:2400]}\n"""\n\n'
        f"Bu belgeye dayanarak bir {label} hazırla. Belgedeki taraf, birim, esas/karar numarası, tarih ve "
        "tutarları aynen kullan; belgede olmayan bilgi için […] bırak."
    )
    result = await _run_module(label, system, user_text, user_id, retrieval_query=body.text[:600])
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


@router.get("/status")
def office_ai_status(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    ok, reason = _ocr_available()
    return {"ocr": ok, "ocr_detail": reason or None, "modules": sorted(MODULE_PROMPTS)}
