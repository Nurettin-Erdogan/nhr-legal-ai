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


# Cümle ya da fıkra sonu: nokta, noktalı virgül, iki nokta, ünlem, soru, kapanış parantezi/tırnağı; ardından PDF'ten yapışmış dipnot rakamı olabilir.
_SENTENCE_END = re.compile(r"[.;:!?)»\"”’']\d{0,3}$")
# Başlık bir harfle başlar; yalnız rakam/ayraç satırları ("9298", "——————") başlık sayılmaz.
_CAPTION_START = re.compile(r"^[^\W\d_]")
_MAX_CAPTION_LINES = 3
_MAX_CAPTION_CHARS = 150


def strip_next_article_caption(body: str) -> str:
    """Madde metninin sonuna yapışan bir sonraki maddenin başlığını ("Sözleşmenin feshinde usul") atar.

    Resmî PDF'te madde başlığı "Madde 19 -" satırından ÖNCE gelir; bir sonraki başlık konumuna kadar kesilen metin bu başlığı da taşır.
    Yalnız son satır(lar) cümle sonu işareti taşımayan KISA bir başlık gibiyse atılır; önceki satırlardan biri cümleyle bitmiyorsa
    metne dokunulmaz (gerçek madde metni kesilmesin).
    """
    lines = body.rstrip().split(chr(10))
    dropped = 0
    while (
        dropped < _MAX_CAPTION_LINES
        and len(lines) - dropped > 1
        and _CAPTION_START.search(lines[-1 - dropped].strip())
        and not _SENTENCE_END.search(lines[-1 - dropped].rstrip())
        and len(lines[-1 - dropped].strip()) <= _MAX_CAPTION_CHARS
    ):
        dropped += 1
    if dropped == 0:
        return body
    kept = lines[: len(lines) - dropped]
    # Atılan satırlardan önceki son dolu satır cümleyle bitmiyorsa bu bir başlık değil, kesilmiş metindir.
    last = next((line for line in reversed(kept) if line.strip()), "")
    if not last or not _SENTENCE_END.search(last.rstrip()):
        return body
    return chr(10).join(kept).rstrip()


def extract_article_text(full_text: str, article_no: str) -> str:
    from ingestion.mevzuat.identity import article_headings, canonical_article
    headings = article_headings(full_text)
    wanted = canonical_article(str(article_no))
    for index, heading in enumerate(headings):
        if heading.identity == wanted:
            end = headings[index + 1].start if index + 1 < len(headings) else len(full_text)
            body = normalize_text(full_text[heading.start:end])
            # Son madde değilse metnin sonu sonraki maddenin başlığıdır; sonuncu maddede sonrası yoktur.
            return strip_next_article_caption(body) if index + 1 < len(headings) else body
    return ""


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
