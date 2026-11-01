"""Danıştay Karar Arama'nın resmî public HTTP uçları için istemci."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from http.cookiejar import CookieJar
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.yargitay.portal import CaptchaRequiredError

BASE_URL = "https://karararama.danistay.gov.tr/"
logger = logging.getLogger(__name__)


class DanistayPortalError(RuntimeError):
    """Danıştay portalı kullanılamayan veya beklenmeyen yanıt döndürdü."""


@dataclass(frozen=True, slots=True)
class PortalDecisionRow:
    document_id: str
    chamber: str
    docket_no: str
    decision_no: str
    decision_date: str
    keyword: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PortalDecisionRow:
        return cls(
            document_id=str(value.get("id") or "").strip(),
            chamber=str(value.get("daireKurul") or "").strip(),
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
    normalized = document_id.strip()
    if not normalized:
        raise ValueError("Danıştay doküman kimliği boş olamaz")
    return f"danistay:{normalized}"


def document_url(document_id: str, *, base_url: str = BASE_URL) -> str:
    normalized = document_id.strip()
    if not normalized:
        raise ValueError("Danıştay doküman kimliği boş olamaz")
    return urljoin(base_url.rstrip("/") + "/", f"getDokuman?{urlencode({'id': normalized})}")


def parse_portal_date(value: str) -> date | None:
    normalized = value.strip().split("T", 1)[0]
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(normalized, pattern).date()
        except ValueError:
            continue
    return None


def _metadata_message(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    return " ".join(
        str(value)
        for value in (metadata.get("FMTE"), metadata.get("message"), metadata.get("error"))
        if value
    ).strip()


def _raise_for_captcha(raw: bytes) -> None:
    text = raw.decode("utf-8-sig", errors="replace")
    captcha_enabled = re.search(
        r'id=["\']isDisplayCaptcha["\'][^>]*value=["\'](?:true|1)["\']',
        text,
        flags=re.IGNORECASE,
    )
    if captcha_enabled:
        raise CaptchaRequiredError(
            "Danıştay Karar Arama CAPTCHA doğrulaması istiyor; otomatik aktarım durduruldu."
        )


def _validate_json(payload: Mapping[str, Any]) -> None:
    message = _metadata_message(payload)
    metadata = payload.get("metadata")
    status = str(metadata.get("FMTY") if isinstance(metadata, Mapping) else "").upper()
    if any(marker in message.casefold() for marker in ("captcha", "recaptcha", "displaycaptcha")):
        raise CaptchaRequiredError(
            "Danıştay Karar Arama CAPTCHA doğrulaması istiyor; otomatik aktarım durduruldu."
        )
    if status and status not in {"SUCCESS", "OK"}:
        raise DanistayPortalError(message or f"Danıştay portalı hata durumu döndürdü: {status}")


class DanistayPortalClient:
    """Resmî arama arayüzünün kullandığı anahtarsız, oturumlu istemci."""

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
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json, text/html, */*",
            "Referer": self.base_url,
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
        }
        if data is not None:
            headers["Content-Type"] = "application/json;charset=UTF-8"

        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                _raise_for_captcha(raw)
                return raw
            except HTTPError as exc:
                if exc.code == 429:
                    raise DanistayPortalError(
                        f"Danıştay HTTP 429; kaynak hız sınırı, aktarım beklemeye alınmalı ({url})"
                    ) from exc
                if not is_retryable_status(exc.code) or attempt == self.max_retries:
                    raise DanistayPortalError(f"Danıştay HTTP hatası: {exc.code} ({url})") from exc
                wait = retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                )
                logger.warning("Danıştay HTTP %s; %.1f saniye sonra yeniden denenecek", exc.code, wait)
                time.sleep(wait)
            except URLError as exc:
                if attempt == self.max_retries:
                    raise DanistayPortalError(f"Danıştay bağlantı hatası ({url}): {exc.reason}") from exc
                time.sleep(retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds))
        raise AssertionError("unreachable")

    def begin_detailed_search(self, filters: Mapping[str, Any]) -> None:
        self._request("")
        raw = self._request("detayliArama", body={"data": dict(filters)})
        if raw.lstrip().startswith(b"{"):
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except json.JSONDecodeError as exc:
                raise DanistayPortalError("Danıştay detaylı arama yanıtı okunamadı") from exc
            if isinstance(payload, Mapping):
                _validate_json(payload)

    def search_page(self, filters: Mapping[str, Any]) -> SearchPage:
        raw = self._request("aramadetaylist", body={"data": dict(filters)})
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DanistayPortalError("Danıştay arama ucu JSON olmayan yanıt döndürdü") from exc
        if not isinstance(payload, Mapping):
            raise DanistayPortalError("Danıştay arama ucu JSON nesnesi döndürmedi")
        _validate_json(payload)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise DanistayPortalError("Danıştay arama yanıtında data alanı bulunamadı")
        raw_rows = data.get("data") or []
        if not isinstance(raw_rows, list):
            raise DanistayPortalError("Danıştay karar listesi geçersiz")
        rows = tuple(
            PortalDecisionRow.from_mapping(item)
            for item in raw_rows
            if isinstance(item, Mapping)
        )
        if any(not row.document_id for row in rows):
            raise DanistayPortalError("Danıştay karar listesinde resmî doküman id eksik")
        try:
            total = int(data.get("recordsTotal") or 0)
            filtered = int(data.get("recordsFiltered") or 0)
        except (TypeError, ValueError) as exc:
            raise DanistayPortalError("Danıştay sayfalama metadata'sı geçersiz") from exc
        return SearchPage(rows=rows, records_total=total, records_filtered=filtered)

    def fetch_document_html(self, document_id: str, *, keyword: str = "") -> str:
        query = urlencode({"id": document_id.strip(), "arananKelime": keyword.strip()})
        raw = self._request(f"getDokuman?{query}")
        text = raw.decode("utf-8-sig", errors="replace")
        if not text.strip():
            raise DanistayPortalError(f"Danıştay karar metni boş: {document_id}")
        return text
