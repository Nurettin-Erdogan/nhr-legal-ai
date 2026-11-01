"""Karar metninden esas no, karar no, tarih ve daire çıkarımı.

Bu modül ağ veya tarayıcı kullanmaz; portal HTML'i değişse bile metin
üzerinden çalışmaya devam eder ve testlerle doğrulanabilir.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from ingestion.text import content_hash, normalize_text, tr_casefold
from ingestion.yargitay.models import CourtDecision

DEFAULT_COURT_NAME = "Yargıtay"

_CASE_NUMBER = r"(\d{4})\s*/\s*(\d{1,6})"
_DATE = r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})"

_DOCKET_PATTERNS = (
    re.compile(rf"esas\s*(?:no|numarası)?\s*[:.\-]?\s*{_CASE_NUMBER}"),
    re.compile(rf"{_CASE_NUMBER}\s*e\s*\."),
)

_DECISION_PATTERNS = (
    re.compile(rf"karar\s*(?:no|numarası)?\s*[:.\-]?\s*{_CASE_NUMBER}"),
    re.compile(rf"{_CASE_NUMBER}\s*k\s*\."),
)

_LABELED_DATE_PATTERNS = (
    re.compile(rf"karar\s*tarihi\s*[:.\-]?\s*{_DATE}"),
    re.compile(rf"tarihi\s*[:.\-]?\s*{_DATE}"),
    re.compile(rf"k\s*\.\s*[,;]?\s*{_DATE}"),
)

_BARE_DATE_PATTERN = re.compile(_DATE)

_CHAMBER_PATTERN = re.compile(r"(\d{1,2})\s*\.\s*(hukuk|ceza)\s*dairesi")
_CHAMBER_ABBREVIATION_PATTERN = re.compile(r"(\d{1,2})\s*\.\s*(h|c)\s*d\b")
_ASSEMBLY_PATTERN = re.compile(r"(hukuk|ceza|büyük)\s+genel\s+kurulu")

_SLUG_SEPARATOR = re.compile(r"[^a-z0-9]+")

_CHAMBER_KIND_NAMES = {
    "hukuk": "Hukuk",
    "ceza": "Ceza",
    "h": "Hukuk",
    "c": "Ceza",
    "büyük": "Büyük",
}


def _first_case_number(text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return f"{match.group(1)}/{int(match.group(2))}"
    return None


def parse_docket_no(text: str) -> str | None:
    """`2019/1234` biçiminde esas numarasını döndürür."""
    return _first_case_number(tr_casefold(text), _DOCKET_PATTERNS)


def parse_decision_no(text: str) -> str | None:
    """`2021/5678` biçiminde karar numarasını döndürür."""
    return _first_case_number(tr_casefold(text), _DECISION_PATTERNS)


def _to_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def parse_decision_date(text: str, *, allow_unlabeled: bool = False) -> date | None:
    """Karar tarihini ayrıştırır.

    `allow_unlabeled` yalnızca liste başlıkları gibi tek tarih içeren kısa
    metinler için açılmalıdır; karar gövdesinde etiketsiz tarihler çoğunlukla
    olay tarihidir.
    """
    folded = tr_casefold(text)

    for pattern in _LABELED_DATE_PATTERNS:
        match = pattern.search(folded)
        if match:
            parsed = _to_date(*match.groups())
            if parsed:
                return parsed

    if not allow_unlabeled:
        return None

    match = _BARE_DATE_PATTERN.search(folded)
    return _to_date(*match.groups()) if match else None


def parse_chamber(text: str) -> str | None:
    """`9. Hukuk Dairesi` veya `Hukuk Genel Kurulu` biçimine normalleştirir.

    Genel kurul, temyiz edilen dairenin adından önce gelir. Aksi halde
    `Ceza Genel Kurulu 2004/8-130` gövdesindeki `8. Ceza Dairesi` HGK/CGK
    kaydını yanlış etiketler.
    """
    folded = tr_casefold(text)
    assembly = _ASSEMBLY_PATTERN.search(folded)
    if assembly:
        return f"{_CHAMBER_KIND_NAMES[assembly.group(1)]} Genel Kurulu"

    match = _CHAMBER_PATTERN.search(folded) or _CHAMBER_ABBREVIATION_PATTERN.search(folded)
    if match:
        kind = _CHAMBER_KIND_NAMES[match.group(2)]
        return f"{int(match.group(1))}. {kind} Dairesi"

    return None


def _slugify(value: str) -> str:
    folded = tr_casefold(value)
    replaced = (
        folded.replace("ı", "i")
        .replace("ş", "s")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    return _SLUG_SEPARATOR.sub("-", replaced).strip("-")


def build_external_id(
    court_name: str,
    chamber: str | None,
    docket_no: str,
    decision_no: str,
) -> str:
    """Aynı karar için her çalıştırmada aynı değeri üreten tekilleştirme anahtarı."""
    return "/".join(
        (
            _slugify(court_name),
            _slugify(chamber) if chamber else "genel",
            docket_no.replace("/", "-"),
            decision_no.replace("/", "-"),
        )
    )


def build_title(
    court_name: str,
    chamber: str | None,
    docket_no: str,
    decision_no: str,
    decision_date: date | None,
) -> str:
    """Kaynak gösteriminde kullanılacak insan tarafından okunabilir başlık."""
    authority = f"{court_name} {chamber}" if chamber else court_name
    title = f"{authority}, E. {docket_no}, K. {decision_no}"
    if decision_date:
        title = f"{title} ({decision_date.strftime('%d.%m.%Y')})"
    return title


def parse_decision(
    *,
    header_text: str = "",
    body_text: str = "",
    source_url: str | None = None,
    court_name: str = DEFAULT_COURT_NAME,
    fallback_chamber: str | None = None,
    scraped_at: datetime | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> CourtDecision | None:
    """Başlık ve gövde metninden karar üretir.

    Esas veya karar numarası bulunamazsa kayıt tekilleştirilemeyeceği için
    `None` döner; uydurma numara üretilmez.
    """
    header = normalize_text(header_text)
    body = normalize_text(body_text)
    combined = f"{header}\n\n{body}".strip()

    docket_no = parse_docket_no(header) or parse_docket_no(body)
    decision_no = parse_decision_no(header) or parse_decision_no(body)

    if not docket_no or not decision_no:
        return None

    decision_date = (
        parse_decision_date(header, allow_unlabeled=True)
        or parse_decision_date(body)
    )
    chamber = parse_chamber(header) or parse_chamber(body) or fallback_chamber
    raw_text = body or combined

    return CourtDecision(
        court_name=court_name,
        chamber=chamber,
        docket_no=docket_no,
        decision_no=decision_no,
        decision_date=decision_date,
        title=build_title(court_name, chamber, docket_no, decision_no, decision_date),
        raw_text=raw_text,
        external_id=build_external_id(court_name, chamber, docket_no, decision_no),
        content_hash=content_hash(raw_text),
        source_url=source_url,
        scraped_at=scraped_at,
        metadata={"header_info": header, **(extra_metadata or {})},
    )
