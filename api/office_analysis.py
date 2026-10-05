"""Belge analizi / toplu özet (yapıştırılan metin): doğrulanmış özet + belgede geçen olgular + kodla listelenen resmî kaynaklar.

Model hukuki değerlendirme yazmaz: yalnız belge metnini özetler ve çıktı kodda belgeyle doğrulanır (`case_summary.verify_summary`).
Hukuki dayanaklar modele yazdırılmaz; korpustan getirilen resmî doğrulanmış mevzuat ve kararlar "otomatik bulundu" diye listelenir.
"""

from __future__ import annotations

import re

from api.case_summary import DocumentSummary, extract_facts, summarize_document
from api.draft_documents import legal_references

MAX_DOCUMENTS = 4
MAX_WINDOWS = 2  # eşzamanlı istek: belge başına ~2 model çağrısı + birleştirme
_MARKER = re.compile(r"^\s*={2,}\s*BELGE\s*(\d+)\s*[:\-]?\s*(.*?)\s*={2,}\s*$", re.IGNORECASE | re.MULTILINE)


def split_documents(text: str) -> list[tuple[str, str]]:
    """"=== BELGE 1: Kira Sözleşmesi ===" işaretleriyle ayrılmış metni (ad, metin) çiftlerine böler; işaret yoksa tek belge."""
    matches = list(_MARKER.finditer(text))
    if not matches:
        return [("Belge", text.strip())]
    documents = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        name = match.group(2) or f"Belge {match.group(1)}"
        body = text[match.end():end].strip()
        if body:
            documents.append((name, body))
    return documents or [("Belge", text.strip())]


def _facts_line(facts: dict) -> str:
    parts = []
    for label, key in (("Tarihler", "dates"), ("Tutarlar", "amounts"), ("Kanun no", "laws")):
        if facts[key]:
            parts.append(f"{label}: {', '.join(facts[key])}")
    docket = [f"E. {value}" for value in facts["esas"]] + [f"K. {value}" for value in facts["karar"]] + facts["numbers"]
    if docket:
        parts.append(f"Esas/Karar: {', '.join(docket)}")
    return " · ".join(parts)


async def analyze(text: str, generate, contexts, *, title: str = "Belge analizi") -> tuple[str, list[dict]]:
    """(markdown, kaynak listesi). Belge sayısı ve uzunluk sınırlıdır; sınır dışı kalan kısım söylenir."""
    import uuid

    documents = split_documents(text)
    skipped = max(0, len(documents) - MAX_DOCUMENTS)
    lines = [f"# {title}", "", "_Yapay zekâ özetidir ve belgeyle karşılaştırılmalıdır. Hukuki değerlendirme içermez; resmî kaynak ya da hukuki görüş yerine geçmez._", ""]
    for index, (name, body) in enumerate(documents[:MAX_DOCUMENTS], start=1):
        try:
            result = await summarize_document(uuid.uuid4(), name, body, ocr=False, generate=generate, max_windows=MAX_WINDOWS)
        except Exception:  # noqa: BLE001 - bir belgenin hatası diğerlerini durdurmaz
            result = DocumentSummary(uuid.uuid4(), name, error="Özet üretilemedi.")
        lines.append(f"## {index}. {name}")
        if result.coverage < 0.999:
            lines.append(f"_Belgenin yaklaşık %{round(result.coverage * 100)}'i özetlendi._")
        if result.error:
            lines.append(f"_{result.error}_")
        lines.extend(f"- {bullet}" for bullet in result.bullets)
        if result.dropped:
            lines.append(f"_{result.dropped} madde belgeyle eşleşmediği için gösterilmedi._")
        facts = _facts_line(extract_facts(body))
        if facts:
            lines.extend(["", f"**Belgede geçen olgular:** {facts}"])
        lines.append("")
    if skipped:
        lines.append(f"_{skipped} belge sınır nedeniyle işlenmedi (en çok {MAX_DOCUMENTS})._\n")
    legal = legal_references(contexts)
    lines.append("## İlgili resmî kaynaklar (otomatik arama)")
    if legal.statutes or legal.decisions:
        lines.append("_Bu liste metne benzer kaynakları bulur; belgenin bu kaynaklara dayandığı ya da uyduğu anlamına gelmez._")
        lines.extend(f"- {line}" for line in legal.statutes + legal.decisions)
    else:
        lines.append("_Korpusta bu metinle eşleşen doğrulanmış kaynak bulunamadı._")
    return "\n".join(lines).rstrip() + "\n", legal.sources
