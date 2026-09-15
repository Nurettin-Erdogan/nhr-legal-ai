from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from http.cookiejar import CookieJar
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ingestion.text import html_to_text

__all__ = [
    "BASE_URL",
    "CaptchaRequiredError",
    "PortalDecisionRow",
    "PortalError",
    "SearchPage",
    "YargitayPortalClient",
    "document_url",
    "html_to_text",
    "parse_portal_date",
    "portal_external_id",
]


BASE_URL = "https://karararama.yargitay.gov.tr/"
logger = logging.getLogger(__name__)


class PortalError(RuntimeError):
    """Yargitay portal returned an unusable response."""


class CaptchaRequiredError(PortalError):
    """The official portal requires an interactive CAPTCHA."""


@dataclass(frozen=True, slots=True)
class PortalDecisionRow:
    document_id: str
    chamber: str
    docket_no: str
    decision_no: str
    decision_date: str
    keyword: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PortalDecisionRow":
        return cls(
            document_id=str(value.get("id") or "").strip(),
            chamber=str(value.get("daire") or "").strip(),
            docket_no=str(value.get("esasNo") or "").strip(),
            decision_no=str(value.get("kararNo") or "").strip(),
            decision_date=str(value.get("kararTarihi") or "").strip(),
            keyword=str(value.get("arananKelime") or "").strip(),
        )


@dataclass(frozen=True, slots=True)
class SearchPage:
    rows: tuple[PortalDecisionRow, ...]
    records_total: int
    records_filtered: int


def portal_external_id(document_id: str) -> str:
    document_id = document_id.strip()
    if not document_id:
        raise ValueError("Yargitay dokuman kimligi bos olamaz")
    return f"yargitay:{document_id}"


def document_url(document_id: str, *, base_url: str = BASE_URL) -> str:
    return urljoin(base_url, f"getDokuman?{urlencode({'id': document_id})}")


def parse_portal_date(value: str) -> date | None:
    normalized = value.strip().split("T", 1)[0]
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def _retry_wait_seconds(
    attempt: int,
    *,
    base_seconds: float,
    retry_after: str | None = None,
) -> float:
    """Üstel bekleme süresini üretir ve sayısal Retry-After değerini gözetir."""
    wait = max(0.0, base_seconds) * (2 ** max(0, attempt - 1))
    if retry_after:
        try:
            wait = max(wait, float(retry_after))
        except ValueError:
            pass
    return wait


def _metadata_message(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    values = [metadata.get("FMTE"), metadata.get("message"), metadata.get("error")]
    return " ".join(str(value) for value in values if value).strip()


def _validate_response(payload: Mapping[str, Any]) -> None:
    message = _metadata_message(payload)
    metadata = payload.get("metadata")
    status = str(metadata.get("FMTY") if isinstance(metadata, Mapping) else "").upper()
    if any(marker in message.lower() for marker in ("captcha", "recaptcha", "displaycaptcha")):
        raise CaptchaRequiredError(
            "Yargitay karar arama portali CAPTCHA dogrulamasi istiyor; otomatik aktarim durduruldu."
        )
    if status and status not in {"SUCCESS", "OK"}:
        raise PortalError(message or f"Yargitay portali hata durumu dondurdu: {status}")


class YargitayPortalClient:
    """HTTP client for the public endpoints used by the official search UI."""

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

    def _request(self, path: str, *, body: Mapping[str, Any] | None = None) -> bytes:
        url = urljoin(self.base_url, path)
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": self.base_url,
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
        }
        if data is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"

        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == self.max_retries:
                    raise PortalError(f"Yargitay HTTP hatasi: {exc.code} ({url})") from exc
                wait = _retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                )
                logger.warning(
                    "Yargıtay HTTP %s; %.1f saniye sonra yeniden denenecek (%s/%s)",
                    exc.code,
                    wait,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(wait)
            except URLError as exc:
                if attempt == self.max_retries:
                    raise PortalError(f"Yargitay baglanti hatasi ({url}): {exc.reason}") from exc
                wait = _retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                )
                logger.warning(
                    "Yargıtay bağlantısı kurulamadı; %.1f saniye sonra yeniden denenecek (%s/%s)",
                    wait,
                    attempt + 1,
                    self.max_retries,
                )
                time.sleep(wait)
        raise AssertionError("unreachable")

    def _json_request(self, path: str, *, body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        raw = self._request(path, body=body)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PortalError(f"Yargitay beklenmeyen yanit dondurdu: {path}") from exc
        if not isinstance(payload, Mapping):
            raise PortalError(f"Yargitay JSON nesnesi yerine farkli bir yanit dondurdu: {path}")
        _validate_response(payload)
        return payload

    def begin_detailed_search(self, filters: Mapping[str, Any]) -> None:
        self._request("")
        raw = self._request("detayliArama", body={"data": dict(filters)})
        if raw.lstrip().startswith(b"{"):
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except json.JSONDecodeError as exc:
                raise PortalError("Detayli arama baslatma yaniti okunamadi") from exc
            if isinstance(payload, Mapping):
                _validate_response(payload)

    def search_page(self, filters: Mapping[str, Any]) -> SearchPage:
        payload = self._json_request("aramadetaylist", body={"data": dict(filters)})
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise PortalError("Arama yanitinda data alani bulunamadi")
        raw_rows = data.get("data") or []
        if not isinstance(raw_rows, list):
            raise PortalError("Arama yanitindaki karar listesi gecersiz")
        rows = tuple(PortalDecisionRow.from_mapping(row) for row in raw_rows if isinstance(row, Mapping))
        return SearchPage(
            rows=rows,
            records_total=int(data.get("recordsTotal") or 0),
            records_filtered=int(data.get("recordsFiltered") or 0),
        )

    def fetch_document_html(self, document_id: str) -> str:
        payload = self._json_request(f"getDokuman?{urlencode({'id': document_id})}")
        value = payload.get("data")
        if not isinstance(value, str) or not value.strip():
            raise PortalError(f"Karar metni bos veya gecersiz: {document_id}")
        return value
