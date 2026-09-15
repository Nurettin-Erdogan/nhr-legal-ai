"""Resmî Gazete'nin public arama ucuyla mevzuat künyesi doğrulama.

Bu modül Resmî Gazete içeriğini ikinci bir mevzuat kopyası olarak yazmaz.
Bedesten'den gelen tarih/sayı/kanun numarasını resmî arşiv kaydıyla
karşılaştırır ve denetlenebilir bir doğrulama sonucu üretir.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from http.cookiejar import CookieJar
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.text import html_to_text, normalize_text, tr_casefold

BASE_URL = "https://www.resmigazete.gov.tr/"
FILTER_PATH = "Home/Filter"
_ALLOWED_HOSTS = {"resmigazete.gov.tr", "www.resmigazete.gov.tr"}
_ISSUE_NO = re.compile(r"\bsay[\u0131i]\s*:\s*(\d{1,6})\b", re.IGNORECASE)
_HTML_CHARSET = re.compile(br"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
logger = logging.getLogger(__name__)


class ResmiGazeteError(RuntimeError):
    """Resmî Gazete yanıtı erişilemez veya sözleşmeye uymaz."""


@dataclass(frozen=True, slots=True)
class GazetteIssue:
    publication_date: date
    issue_no: str | None
    archive_url: str
    title: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class GazetteVerification:
    verified: bool
    archive_url: str | None
    requested_date: str | None
    observed_date: str
    requested_issue_no: str | None
    observed_issue_no: str | None
    law_no: str
    law_no_present: bool
    law_name_present: bool
    verified_at: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def parse_portal_date(value: Any) -> date | None:
    text = str(value or "").strip().split("T", 1)[0]
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _normalize_issue_no(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text == "0":
        return None
    return text


def _official_archive_url(value: Any, *, base_url: str) -> str:
    url = urljoin(base_url, str(value or "").strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ResmiGazeteError("Resmî Gazete arama sonucu resmî olmayan URL döndürdü")
    return url


def _decode_archive_html(raw: bytes) -> str:
    declared = _HTML_CHARSET.search(raw[:4096])
    encodings = []
    if declared:
        encodings.append(declared.group(1).decode("ascii", errors="ignore"))
    encodings.extend(("utf-8", "windows-1254", "iso-8859-9"))
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


class ResmiGazeteClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_seconds: float = 30,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.opener = opener or build_opener(HTTPCookieProcessor(CookieJar()))

    def _request(self, url: str, *, body: Mapping[str, Any] | None = None) -> bytes:
        data = None
        headers = {
            "Accept": "application/json, text/html, */*",
            "Referer": self.base_url,
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-verification)",
        }
        if body is not None:
            data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                if not is_retryable_status(exc.code) or attempt == self.max_retries:
                    raise ResmiGazeteError(f"Resmî Gazete HTTP hatası: {exc.code} ({url})") from exc
                wait = retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                )
                logger.warning("Resmî Gazete HTTP %s; %.1f saniye sonra yeniden denenecek", exc.code, wait)
                time.sleep(wait)
            except URLError as exc:
                if attempt == self.max_retries:
                    raise ResmiGazeteError(f"Resmî Gazete bağlantı hatası: {exc.reason}") from exc
                time.sleep(retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds))
        raise AssertionError("unreachable")

    def search_legislation(
        self,
        *,
        law_no: str,
        publication_date: date | None = None,
        expected_issue_no: str | None = None,
    ) -> GazetteIssue:
        # Ana sayfa isteği public arama oturumunu/cookie'lerini kurar.
        self._request(self.base_url)
        parameters = {
            "searchtype": "1",
            "genelaranacakkelime": "",
            "genelbaslangictarihi": publication_date.isoformat() if publication_date else "",
            "genelbitistarihi": publication_date.isoformat() if publication_date else "",
            "genelsayi": str(expected_issue_no or ""),
            "genelmevzuatsayisi": law_no.strip(),
            "genelmukerrer": "",
            "genelmevzuatturu": "",
            "genelkurumkodu": "",
        }
        body = {"draw": 1, "start": 0, "length": 10, "parameters": parameters}
        raw = self._request(urljoin(self.base_url, FILTER_PATH), body=body)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResmiGazeteError("Resmî Gazete arama ucu JSON olmayan yanıt döndürdü") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise ResmiGazeteError("Resmî Gazete arama yanıtı beklenen sözleşmede değil")
        candidates = []
        for item in payload["data"]:
            if not isinstance(item, Mapping):
                continue
            observed_date = parse_portal_date(item.get("resmiGazeteTarihi"))
            observed_issue = _normalize_issue_no(item.get("resmiGazeteSayisi"))
            observed_law_no = str(item.get("kanunKararNo") or "").strip()
            if publication_date and observed_date != publication_date:
                continue
            if expected_issue_no and observed_issue != _normalize_issue_no(expected_issue_no):
                continue
            if observed_law_no != law_no.strip():
                continue
            candidates.append(item)
        if len(candidates) != 1:
            raise ResmiGazeteError(
                f"{law_no} numaralı mevzuat için tekil Resmî Gazete kaydı bulunamadı"
            )
        item = candidates[0]
        observed_date = parse_portal_date(item.get("resmiGazeteTarihi"))
        if observed_date is None:
            raise ResmiGazeteError("Resmî Gazete arama sonucunda yayın tarihi eksik")
        archive_url = _official_archive_url(item.get("url"), base_url=self.base_url)
        archive_html = _decode_archive_html(self._request(archive_url))
        raw_text = normalize_text(html_to_text(archive_html))
        if not raw_text:
            raise ResmiGazeteError("Resmî Gazete arşiv sayfasından metin ayrıştırılamadı")
        issue_no = _normalize_issue_no(item.get("resmiGazeteSayisi"))
        if issue_no is None:
            match = _ISSUE_NO.search(raw_text)
            issue_no = match.group(1) if match else None
        return GazetteIssue(
            publication_date=observed_date,
            issue_no=issue_no,
            archive_url=archive_url,
            title=str(item.get("konu") or "").strip(),
            raw_text=raw_text,
        )

    def verify_legislation(
        self,
        *,
        publication_date: date | None,
        issue_no: str | None,
        law_no: str,
        law_name: str,
    ) -> GazetteVerification:
        issue = self.search_legislation(
            law_no=law_no,
            publication_date=publication_date,
            expected_issue_no=issue_no,
        )
        folded = tr_casefold(issue.raw_text)
        normalized_law_no = law_no.strip()
        law_no_present = bool(
            normalized_law_no
            and re.search(rf"(?<!\d){re.escape(normalized_law_no)}(?!\d)", issue.raw_text)
        )
        normalized_name = normalize_text(law_name)
        law_name_present = bool(normalized_name and tr_casefold(normalized_name) in folded)
        requested_issue = _normalize_issue_no(issue_no)
        issue_matches = requested_issue is None or requested_issue == issue.issue_no
        date_matches = publication_date is None or publication_date == issue.publication_date
        verified = issue_matches and date_matches and law_no_present
        reasons = []
        if not issue_matches:
            reasons.append(f"sayı uyuşmuyor: beklenen={requested_issue}, bulunan={issue.issue_no}")
        if not law_no_present:
            reasons.append(f"{normalized_law_no} numarası arşiv sayfasında yok")
        if not date_matches:
            reasons.append(
                f"tarih uyuşmuyor: beklenen={publication_date}, bulunan={issue.publication_date}"
            )
        detail = "Resmî Gazete tarih/sayı ve mevzuat numarası doğrulandı" if verified else "; ".join(reasons)
        return GazetteVerification(
            verified=verified,
            archive_url=issue.archive_url,
            requested_date=publication_date.isoformat() if publication_date else None,
            observed_date=issue.publication_date.isoformat(),
            requested_issue_no=requested_issue,
            observed_issue_no=issue.issue_no,
            law_no=normalized_law_no,
            law_no_present=law_no_present,
            law_name_present=law_name_present,
            verified_at=datetime.now(UTC).isoformat(),
            detail=detail,
        )
