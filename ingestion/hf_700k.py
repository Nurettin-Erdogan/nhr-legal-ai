"""HuggingFace 700k derlemesini legal_sources satırına dönüştürür.

Üçüncü taraf tohumudur; resmi doğrulanmış sayılmaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ingestion.danistay import parser as danistay_parser
from ingestion.danistay.portal import document_url as danistay_document_url
from ingestion.danistay.portal import portal_external_id as danistay_external_id
from ingestion.text import content_hash, normalize_text, tr_casefold
from ingestion.yargitay.parser import build_title, parse_chamber as parse_yargitay_chamber
from ingestion.yargitay.portal import document_url as yargitay_document_url
from ingestion.yargitay.portal import portal_external_id as yargitay_external_id

HF_DATASET = "erdem-erdem/Turkish-Law-Documents-700k-clustered"
PROVENANCE = "bulk_seed"
INGESTION_METHOD = "bulk_seed"
CANONICAL_SOURCE_NAME = "HuggingFace Turkish-Law-Documents-700k-clustered"
OVERSIZED_CHARS = 200_000
CHAMBER_HEADER_CHARS = 800

_CASE_NO = re.compile(r"^(\d{4})\s*/\s*(\d{1,2}-\d{1,6}|\d{1,6})$")
_DATE = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$")
_HTML = re.compile(r"</?(html|body|div|span|p|br|table|tr|td|script)\b", re.I)
_CAPTCHA = re.compile(
    r"captcha|recaptcha|displaycaptcha|güvenlik doğrulama|guvenlik dogrulama",
    re.I,
)
_ERROR_PAGE = re.compile(
    r"access denied|error page|sayfa bulunamadı|belge alma islem(?:i|inde) hata|"
    r"runtime exception|cloudflare|just a moment",
    re.I,
)
_MOJIBAKE = re.compile(r"Ã.|Ä.|Å.|â€™|â€|�|\ufffd")


@dataclass(frozen=True, slots=True)
class PreparedRow:
    dataset_id: str
    source_code: str
    court_name: str
    chamber: str
    docket_no: str
    decision_no: str
    decision_date: date | None
    external_id: str
    title: str
    raw_text: str
    content_hash: str
    source_url: str | None
    oversized: bool
    quarantine_code: str | None
    quarantine_reason: str | None
    metadata: dict[str, object]


def court_of(source: str) -> str:
    if str(source).startswith("ygty"):
        return "Yargıtay"
    if str(source).startswith("dnsy"):
        return "Danıştay"
    return ""


def parse_case_no(value: object) -> str | None:
    text = str(value or "").strip()
    match = _CASE_NO.match(text)
    if not match:
        return None
    year, rest = match.group(1), match.group(2)
    if "-" in rest:
        return f"{year}/{rest}"
    return f"{year}/{int(rest)}"


def parse_date_field(value: object) -> date | None:
    text = str(value or "").strip()
    if text in {"", ".", "-", "—", "null", "None", "nan"}:
        return None
    match = _DATE.match(text)
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def strip_third_party_markup(text: str) -> str:
    cleaned = text.replace("**", "")
    kept: list[str] = []
    for line in cleaned.splitlines():
        folded = tr_casefold(line.strip().strip('"“”'))
        if folded == "içtihat metni":
            continue
        kept.append(line)
    return normalize_text("\n".join(kept))


def parse_chamber(court_name: str, text: str) -> str:
    header = text[:CHAMBER_HEADER_CHARS]
    if court_name == "Danıştay":
        return danistay_parser.parse_chamber(header) or danistay_parser.parse_chamber(text) or ""
    return parse_yargitay_chamber(header) or parse_yargitay_chamber(text) or ""


def _quarantine(text: str, decision_date: date | None, raw_date: object) -> tuple[str, str] | None:
    if not text.strip():
        return "empty_text", "Karar metni boş"
    if _CAPTCHA.search(text):
        return "captcha_page", "CAPTCHA veya doğrulama sayfası"
    if _ERROR_PAGE.search(text):
        return "error_page", "Hata veya erişim reddi sayfası"
    if _MOJIBAKE.search(text):
        return "broken_encoding", "Bozuk karakter kodlaması"
    if decision_date is None:
        return "missing_date", f"kararTarihi geçersiz: {raw_date!r}"
    if _HTML.search(text) and text.lstrip().lower().startswith("<html"):
        return "html_error_page", "HTML belge; beklenen temiz metin değil"
    return None


def prepare_row(raw: dict[str, object]) -> PreparedRow | None:
    source_code = str(raw.get("source") or "").strip()
    court_name = court_of(source_code)
    dataset_id = jsonable_id(raw.get("id"))
    if not court_name or not dataset_id:
        return PreparedRow(
            dataset_id=dataset_id,
            source_code=source_code,
            court_name=court_name or "unknown",
            chamber="",
            docket_no="",
            decision_no="",
            decision_date=None,
            external_id="",
            title="",
            raw_text="",
            content_hash="",
            source_url=None,
            oversized=False,
            quarantine_code="invalid_identity",
            quarantine_reason="source veya id eksik",
            metadata={"provenance": PROVENANCE},
        )

    docket_no = parse_case_no(raw.get("esasNo")) or ""
    decision_no = parse_case_no(raw.get("kararNo")) or ""
    decision_date = parse_date_field(raw.get("kararTarihi"))
    raw_text = strip_third_party_markup(str(raw.get("text") or ""))
    flagged = _quarantine(raw_text, decision_date, raw.get("kararTarihi"))
    if not flagged and (not docket_no or not decision_no):
        flagged = ("invalid_case_no", "esasNo veya kararNo YEAR/NO değil")

    chamber = parse_chamber(court_name, raw_text) if raw_text else ""
    external_id = (
        yargitay_external_id(dataset_id)
        if court_name == "Yargıtay"
        else danistay_external_id(dataset_id)
    )
    source_url = (
        yargitay_document_url(dataset_id)
        if court_name == "Yargıtay"
        else danistay_document_url(dataset_id)
    )
    title = (
        build_title(court_name, chamber or None, docket_no, decision_no, decision_date)
        if docket_no and decision_no
        else f"{court_name} {dataset_id}"
    )
    digest = content_hash(raw_text) if raw_text else ""
    oversized = len(raw_text) > OVERSIZED_CHARS
    metadata: dict[str, object] = {
        "provenance": PROVENANCE,
        "official_verified": False,
        "third_party": True,
        "source_adapter": "hf_700k",
        "hf_dataset": HF_DATASET,
        "hf_source": source_code,
        "source_document_id": dataset_id,
        "oversized_text": oversized,
        "cluster_ids_omitted": True,
    }
    return PreparedRow(
        dataset_id=dataset_id,
        source_code=source_code,
        court_name=court_name,
        chamber=chamber,
        docket_no=docket_no,
        decision_no=decision_no,
        decision_date=decision_date,
        external_id=external_id,
        title=title,
        raw_text=raw_text,
        content_hash=digest,
        source_url=source_url,
        oversized=oversized,
        quarantine_code=flagged[0] if flagged else None,
        quarantine_reason=flagged[1] if flagged else None,
        metadata=metadata,
    )


def jsonable_id(value: object) -> str:
    if hasattr(value, "item"):
        value = value.item()
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "", 1).isdigit():
        return text[:-2]
    return text
