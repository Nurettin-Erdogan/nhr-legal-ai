"""Adalet Bakanlığı Bedesten mevzuat JSON uçları."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds

BASE_URL = "https://bedesten.adalet.gov.tr/mevzuat/"
APP_NAME = "UyapMevzuat"


class MevzuatPortalError(RuntimeError):
    """Bedesten mevzuat ucu kullanılamayan bir yanıt döndürdü."""


def is_missing_article_tree_error(message: str) -> bool:
    """Bedesten madde ağacı yok demek; metin uydurulmaz, kanun atlanır."""
    text = (message or "").casefold()
    return (
        "ağaç yapısı mevcut değildir" in message
        or "agac yapisi mevcut degildir" in text
        or "madde ağacı boş" in text
        or "madde agaci bos" in text
    )


@dataclass(frozen=True, slots=True)
class SearchPage:
    documents: tuple[Mapping[str, Any], ...]
    total: int
    start: int


def _metadata_message(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    values = [metadata.get("FMTE"), metadata.get("message"), metadata.get("error")]
    return " ".join(str(value) for value in values if value).strip()


def _validate_response(payload: Mapping[str, Any]) -> None:
    metadata = payload.get("metadata")
    status = str(metadata.get("FMTY") if isinstance(metadata, Mapping) else "").upper()
    if status and status not in {"SUCCESS", "OK"}:
        raise MevzuatPortalError(
            _metadata_message(payload) or f"Bedesten mevzuat ucu hata durumu döndürdü: {status}"
        )


class MevzuatPortalClient:
    """mevzuat.adalet.gov.tr arayüzünün kullandığı anahtarsız JSON uçları."""

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
        self.opener = opener or build_opener()

    def _request(self, path: str, body: Mapping[str, Any], *, paging: bool = False) -> Mapping[str, Any]:
        url = urljoin(self.base_url, path)
        payload: dict[str, Any] = {"data": dict(body), "applicationName": APP_NAME}
        if paging:
            payload["paging"] = True
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "AdaletApplicationName": APP_NAME,
            "Origin": "https://mevzuat.adalet.gov.tr",
            "Referer": "https://mevzuat.adalet.gov.tr/",
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
        }

        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                break
            except HTTPError as exc:
                if exc.code == 429:
                    raise MevzuatPortalError(
                        f"Bedesten HTTP 429; kaynak hız sınırı, aktarım beklemeye alınmalı ({url})"
                    ) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                retryable = is_retryable_status(exc.code)
                if not retryable or attempt == self.max_retries:
                    raise MevzuatPortalError(f"Bedesten HTTP hatası: {exc.code} ({url})") from exc
                wait = retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=retry_after,
                )
                time.sleep(wait)
            except URLError as exc:
                if attempt == self.max_retries:
                    raise MevzuatPortalError(f"Bedesten bağlantı hatası ({url}): {exc.reason}") from exc
                time.sleep(
                    retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds)
                )
        else:
            raise AssertionError("unreachable")

        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MevzuatPortalError(f"Bedesten beklenmeyen yanıt döndürdü: {path}") from exc
        if not isinstance(parsed, Mapping):
            raise MevzuatPortalError(f"Bedesten JSON nesnesi yerine farklı bir yanıt döndürdü: {path}")
        _validate_response(parsed)
        return parsed

    def search_page(
        self,
        *,
        page_number: int,
        page_size: int,
        law_no: str | None = None,
        title: str | None = None,
        types: tuple[str, ...] = ("KANUN",),
    ) -> SearchPage:
        inner: dict[str, Any] = {
            "pageSize": page_size,
            "pageNumber": page_number,
            "sortFields": ["RESMI_GAZETE_TARIHI"],
            "sortDirection": "desc",
        }
        if law_no:
            inner["mevzuatNo"] = law_no
        if title:
            inner["mevzuatAdi"] = title
        if types:
            inner["mevzuatTurList"] = list(types)
        payload = self._request("searchDocuments", inner, paging=True)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MevzuatPortalError("Arama yanıtında data alanı bulunamadı")
        rows = data.get("mevzuatList") or []
        if not isinstance(rows, list):
            raise MevzuatPortalError("Arama yanıtındaki mevzuat listesi geçersiz")
        documents = tuple(row for row in rows if isinstance(row, Mapping))
        return SearchPage(
            documents=documents,
            total=int(data.get("total") or 0),
            start=int(data.get("start") or 0),
        )

    def fetch_article_tree(self, mevzuat_id: str) -> Mapping[str, Any]:
        payload = self._request("mevzuatMaddeTree", {"mevzuatId": mevzuat_id})
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MevzuatPortalError(f"Madde ağacı geçersiz: {mevzuat_id}")
        return data

    def fetch_article_html(self, madde_id: str) -> str:
        payload = self._request(
            "getDocumentContent",
            {"documentType": "MADDE", "id": madde_id},
        )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise MevzuatPortalError(f"Madde içeriği geçersiz: {madde_id}")
        raw = data.get("content")
        mime = str(data.get("mimeType") or "text/html")
        if not isinstance(raw, str) or not raw.strip():
            raise MevzuatPortalError(f"Madde metni boş: {madde_id}")
        if mime.lower() not in {"text/html", "text/plain", "application/xhtml+xml"}:
            raise MevzuatPortalError(f"Madde beklenen HTML yerine {mime} döndü: {madde_id}")
        try:
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception as exc:
            raise MevzuatPortalError(f"Madde içeriği çözülemedi: {madde_id}") from exc
