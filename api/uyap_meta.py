"""UYAP çıktıları için dosya adı temizleme, üst veri tahmini ve metin örneği (web/src/lib/uyap.ts karşılığı).

Güvenlik notu: UYAP'ın açık bir API'si yoktur ve e-imza/kimlik bilgileri üçüncü bir sisteme verilemez;
akış, kullanıcının indirdiği resmî çıktının içe aktarılması üzerine kuruludur. Buradaki üst veri
yalnızca **tahmindir** ve kullanıcıya öyle gösterilmelidir.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import date
from typing import TypedDict

from api.udf import extract_udf_text

ALLOWED_EXTENSIONS = frozenset(
    {"pdf", "udf", "odt", "docx", "doc", "txt", "html", "tif", "tiff", "jpg", "jpeg", "png", "xml", "eyp"}
)
MAX_FILE_BYTES = 50 * 1024 * 1024

_BIRIM_RE = re.compile(
    r"((?:\d+\.\s*)?(?:asliye\s+(?:hukuk|ticaret|ceza)|sulh\s+hukuk|i(?:ş|s)\s+mahkemesi|aile\s+mahkemesi"
    r"|icra\s+(?:müdürlü(?:ğ|g)ü|hukuk)|a(?:ğ|g)(?:ı|i)r\s+ceza|tüketici"
    r"|cumhuriyet\s+ba(?:ş|s)savc(?:ı|i)l(?:ı|i)(?:ğ|g)(?:ı|i))[\w\s.]{0,25})",
    re.IGNORECASE,
)
_DOC_TYPES = (
    "dilekçe", "dilekce", "tensip", "karar", "gerekçeli", "gerekceli", "tebligat", "bilirkişi",
    "bilirkisi", "duruşma", "durusma", "tutanak", "müzekkere", "muzekkere", "haciz", "ödeme emri",
    "odeme emri", "vekaletname", "layiha", "cevap", "temyiz", "istinaf", "rapor", "makbuz",
)
_FILE_NO_RE = re.compile(r"\b(20\d{2})\s*[/_-]\s*(\d{1,7})\b")
_DATE_DMY_RE = re.compile(r"\b(\d{2})[.\-/](\d{2})[.\-/](20\d{2})\b")
_DATE_YMD_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


class UyapMeta(TypedDict):
    uyap_file_no: str | None
    uyap_birim: str | None
    doc_date: str | None
    doc_type: str | None


def extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def is_allowed_file(name: str) -> bool:
    return extension_of(name) in ALLOWED_EXTENSIONS


def safe_file_name(name: str) -> str:
    """Depolama yolu için güvenli ad: dizin geçişi ve özel karakterler temizlenir."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKD", base)
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.ASCII)
    base = re.sub(r"_{2,}", "_", base)
    return base[-120:] or "dosya"


def _valid_date(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_uyap_meta(file_name: str, sample: str = "") -> UyapMeta:
    haystack = f"{re.sub(r'[_-]+', ' ', file_name)} {sample[:4000]}"
    file_no = _FILE_NO_RE.search(haystack)
    doc_date = None
    dmy = _DATE_DMY_RE.search(haystack)
    if dmy:
        doc_date = _valid_date(dmy.group(3), dmy.group(2), dmy.group(1))
    else:
        ymd = _DATE_YMD_RE.search(haystack)
        if ymd:
            doc_date = _valid_date(ymd.group(1), ymd.group(2), ymd.group(3))
    lowered = haystack.lower()
    doc_type = next((t for t in _DOC_TYPES if t in lowered), None)
    birim = _BIRIM_RE.search(haystack)
    return {
        "uyap_file_no": f"{file_no.group(1)}/{file_no.group(2)}" if file_no else None,
        "uyap_birim": re.sub(r"\s+", " ", birim.group(1).strip()) if birim else None,
        "doc_date": doc_date,
        "doc_type": doc_type[0].upper() + doc_type[1:] if doc_type else None,
    }


def extract_text_sample(name: str, data: bytes, limit: int = 20000) -> str:
    """Metin, UDF (içinde content.xml olan zip), PDF ve DOCX dosyalarından kısa bir metin örneği çıkarır."""
    ext = extension_of(name)
    try:
        if ext in ("txt", "xml"):
            return data[:limit].decode("utf-8", errors="ignore")
        if ext == "html":
            from ingestion.text import decode_html_bytes, html_to_text

            return html_to_text(decode_html_bytes(data[:limit * 4]))[:limit]
        if ext in ("udf", "odt"):  # ikisi de içinde content.xml olan zip (UYAP ön izleme evrakı ODT gelir)
            return extract_udf_text(data, limit)
        if ext == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            parts: list[str] = []
            for page in reader.pages[:10]:
                parts.append(page.extract_text() or "")
                if sum(len(p) for p in parts) >= limit:
                    break
            return "\n".join(parts)[:limit]
        if ext == "docx":
            from docx import Document

            document = Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs)[:limit]
    except Exception:  # noqa: BLE001 - metin ayıklanamazsa belge yine de kaydedilir
        return ""
    return ""
