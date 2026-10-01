"""MBS'nin resmî PDF metniyle tek bir mevzuat maddesini doğrula."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, build_opener

from pypdf import PdfReader

from ingestion.text import html_to_text, normalize_text, tr_casefold

_ALLOWED_HOSTS = {"mevzuat.gov.tr", "www.mevzuat.gov.tr"}
_MAX_PDF_BYTES = 20 * 1024 * 1024
_FOOTNOTE_MARKER = re.compile(r"\[\d+\]")
_PDF_FOOTNOTE_LINE = re.compile(
    r"(?m)^\s*\d+\s+\d{1,2}/\d{1,2}/\d{4}.*$"
)
_NON_WORD = re.compile(r"\W+")


class MbsTextVerificationError(RuntimeError):
    """Resmî MBS PDF'si güvenle indirilemedi veya ayrıştırılamadı."""


@dataclass(frozen=True, slots=True)
class ArticleTextVerification:
    verified: bool
    ratio: float
    official_article: str


def _validate_pdf_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_HOSTS
        or not parsed.path.casefold().startswith("/mevzuatmetin/")
        or not parsed.path.casefold().endswith(".pdf")
    ):
        raise MbsTextVerificationError("MBS PDF adresi resmî değil")


def fetch_official_pdf_text(
    url: str,
    *,
    timeout_seconds: float = 10,
    opener: Any | None = None,
) -> str:
    _validate_pdf_url(url)
    request = Request(
        url,
        headers={
            "Accept": "application/pdf",
            "Referer": "https://www.mevzuat.gov.tr/",
            "User-Agent": "nhr-legal-ai/0.1 (official-text-verification)",
        },
    )
    try:
        with (opener or build_opener()).open(
            request, timeout=timeout_seconds
        ) as response:
            payload = response.read(_MAX_PDF_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - tek ve güvenli alan hatasına çevrilir
        raise MbsTextVerificationError(f"MBS PDF indirilemedi: {exc}") from exc
    if len(payload) > _MAX_PDF_BYTES or not payload.startswith(b"%PDF"):
        raise MbsTextVerificationError("MBS beklenen PDF belgesini döndürmedi")
    try:
        reader = PdfReader(BytesIO(payload))
        return normalize_text(
            "\n".join((page.extract_text() or "") for page in reader.pages)
        )
    except Exception as exc:  # noqa: BLE001
        raise MbsTextVerificationError(f"MBS PDF metni ayrıştırılamadı: {exc}") from exc


def extract_article_text(full_text: str, article_no: str) -> str:
    number = re.escape(str(article_no).strip())
    heading = re.compile(
        rf"(?im)^\s*(?:(?:ek|ge[çc]ici)\s+)?madde\s+{number}\b"
    )
    match = heading.search(full_text)
    if match is None:
        return ""
    next_heading = re.compile(
        r"(?im)^\s*(?:(?:ek|ge[çc]ici)\s+)?madde\s+\d{1,4}[a-zA-Z]?\b"
    ).search(full_text, match.end())
    end = next_heading.start() if next_heading else len(full_text)
    return normalize_text(full_text[match.start() : end])


def _comparison_key(text: str) -> str:
    normalized = normalize_text(html_to_text(text))
    normalized = _FOOTNOTE_MARKER.sub("", normalized)
    normalized = _PDF_FOOTNOTE_LINE.sub("", normalized)
    return _NON_WORD.sub("", tr_casefold(normalized))


def verify_article_text(
    seed_text: str,
    official_pdf_text: str,
    *,
    article_no: str,
    minimum_ratio: float = 0.93,
) -> ArticleTextVerification:
    official_article = extract_article_text(official_pdf_text, article_no)
    seed_key = _comparison_key(seed_text)
    official_key = _comparison_key(official_article)
    if len(seed_key) < 200 or len(official_key) < 200:
        return ArticleTextVerification(False, 0.0, official_article)
    ratio = SequenceMatcher(
        None,
        seed_key,
        official_key,
        autojunk=False,
    ).ratio()
    return ArticleTextVerification(
        verified=ratio >= minimum_ratio,
        ratio=ratio,
        official_article=official_article,
    )
