"""KDK Kararlar Bilgi Bankası'nın doğrulanmış public arama/PDF istemcisi."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import date
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener
import http.cookiejar

from ingestion.http import is_retryable_status, retry_wait_seconds

BASE_URL = "https://kararlar.ombudsman.gov.tr/"
_ALLOWED_HOST = "kararlar.ombudsman.gov.tr"


class KdkPortalError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SearchPage:
    rows: tuple[dict[str, Any], ...]
    records_total: int
    records_filtered: int
    start: int


def _official_url(path: str, *, base_url: str = BASE_URL) -> str:
    url = urljoin(base_url, path)
    if urlparse(url).hostname != _ALLOWED_HOST:
        raise KdkPortalError("KDK kaynağı resmî alan adına ait değil")
    return url


def download_url(publication_path: str, decision_date: str, *, base_url: str = BASE_URL) -> str:
    if not publication_path.strip() or not decision_date.strip():
        raise KdkPortalError("KDK PDF yolu veya karar tarihi eksik")
    query = urlencode({"url": publication_path, "tarih": decision_date})
    return _official_url(f"Arama/Download?{query}", base_url=base_url)


def search_form(
    *,
    start: int,
    length: int,
    keyword: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, str]:
    return {
        "draw": "1",
        "start": str(max(0, start)),
        "length": str(max(1, length)),
        "order[0][column]": "0",
        "order[0][dir]": "desc",
        "basbas": "",
        "basbit": "",
        "basnoyil": "",
        "basnosayi": "",
        "sikayetkonu": "",
        "konuidarekelimeleri": "",
        "karbas": date_from.strftime("%d/%m/%Y") if date_from else "",
        "karbit": date_to.strftime("%d/%m/%Y") if date_to else "",
        "kararTuru": "",
        "evrakkonu": "",
        "kararkelimeleri": keyword.strip(),
        "ortakalankelimeleri": "",
    }


class KdkPortalClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_seconds: float = 30,
        max_retries: int = 3,
        retry_backoff_seconds: float = 2.0,
        opener: Any | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(1, max_retries)
        self.retry_backoff_seconds = retry_backoff_seconds
        if opener is None:
            jar = http.cookiejar.CookieJar()
            opener = build_opener(HTTPCookieProcessor(jar))
        self.opener = opener

    def _request(self, path: str, *, data: dict[str, str] | None = None) -> bytes:
        url = _official_url(path, base_url=self.base_url)
        body = urlencode(data).encode("utf-8") if data is not None else None
        headers = {
            "User-Agent": "NHR-Legal-AI/1.0 (+official-public-source)",
            "Accept": "application/json, application/pdf, text/html;q=0.9, */*;q=0.8",
        }
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"
        request = Request(url, data=body, headers=headers)
        for attempt in range(1, self.max_retries + 1):
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except HTTPError as exc:
                if not is_retryable_status(exc.code) or attempt == self.max_retries:
                    raise KdkPortalError(f"KDK HTTP hatası: {exc.code} ({url})") from exc
                wait = retry_wait_seconds(
                    attempt,
                    base_seconds=self.retry_backoff_seconds,
                    retry_after=exc.headers.get("Retry-After"),
                )
            except (URLError, TimeoutError, socket.timeout) as exc:
                if attempt == self.max_retries:
                    raise KdkPortalError(f"KDK bağlantı hatası ({url}): {exc}") from exc
                wait = retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds)
            sleep(wait)
        raise AssertionError("unreachable")

    def begin_search(self, keyword: str = "") -> None:
        self._request("")
        if keyword.strip():
            encoded = quote(keyword.strip())
            self._request(f"Home/Ara?aramatext={encoded}")
            self._request(f"Arama/AramaFiltre?param={encoded}")

    def search_page(self, form: dict[str, str]) -> SearchPage:
        raw = self._request("Arama/IndexPaging", data=form)
        try:
            payload = json.loads(raw.decode("utf-8"))
            rows = payload["data"]
            total = int(payload["recordsTotal"])
            filtered = int(payload["recordsFiltered"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise KdkPortalError("KDK arama yanıtı beklenen JSON sözleşmesine uymuyor") from exc
        if not isinstance(rows, list):
            raise KdkPortalError("KDK arama satırları liste değil")
        return SearchPage(tuple(rows), total, filtered, int(form.get("start", "0")))

    def download_pdf(self, publication_path: str, decision_date: str) -> tuple[bytes, str]:
        url = download_url(publication_path, decision_date, base_url=self.base_url)
        raw = self._request(url)
        if not raw.startswith(b"%PDF-"):
            raise KdkPortalError("KDK tam metin yanıtı geçerli PDF değil")
        return raw, url
