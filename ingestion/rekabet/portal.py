"""Rekabet Kurumu Kurul kararları (rekabet.gov.tr) resmî site istemcisi.

Liste: `GET /tr/Kararlar?page=<n>` (sayfa başına 10 karar, "Toplam : N" bilgisi ile);
her karar `GET /Karar?kararId=<guid>` adresinden PDF olarak (tam metin) iner.
CAPTCHA/429 aşılmaz; hata olduğunda çağıran bekler.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import lxml.html

BASE_URL = "https://www.rekabet.gov.tr"
USER_AGENT = "nhr-legal-ai/0.1 (official-public-source-ingestion)"
PAGE_SIZE = 10


class RekabetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ListRow:
    karar_id: str
    karar_sayisi: str
    karar_tarihi: str
    yayimlanma_tarihi: str
    karar_turu: str
    konu: str


class RekabetClient:
    def __init__(self, *, delay_seconds: float = 1.5, timeout_seconds: float = 60.0, max_retries: int = 3) -> None:
        self.delay = delay_seconds
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._last = 0.0

    def _pace(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _get(self, path: str) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            request = urllib.request.Request(f"{BASE_URL}{path}", headers={"User-Agent": USER_AGENT})
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise RekabetError("Rekabet HTTP 429; kaynak hız sınırı, beklenmeli") from exc
                if exc.code in {400, 403, 404}:
                    raise RekabetError(f"Rekabet HTTP {exc.code}: {path}") from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
                last = exc
            time.sleep(min(30, 2**attempt))
        raise RekabetError(f"Rekabet isteği başarısız: {last}")

    def list_page(self, page: int) -> tuple[list[ListRow], int]:
        """(satırlar, toplam karar sayısı)."""
        html = self._get(f"/tr/Kararlar?page={page}").decode("utf-8", errors="replace")
        document = lxml.html.fromstring(html)
        total_match = re.search(r"Toplam\s*:\s*(\d+)", document.text_content())
        if total_match is None:
            raise RekabetError("Rekabet liste sayfasında toplam sayısı bulunamadı")
        rows: list[ListRow] = []
        for link in document.xpath('//a[contains(@href,"/Karar?kararId=")]'):
            match = re.search(r"kararId=([0-9a-fA-F-]{36})", link.get("href", ""))
            tables = link.xpath("ancestor::table[1]")
            if not match or not tables:
                continue
            fields: dict[str, str] = {}
            for th in tables[0].xpath(".//th"):
                label = " ".join(th.text_content().replace(":", " ").split())
                value = " ".join(th.xpath("string(following-sibling::td[1])").split())
                if label:
                    fields[label] = value
            rows.append(
                ListRow(
                    karar_id=match.group(1).lower(),
                    karar_sayisi=fields.get("Karar Sayısı", ""),
                    karar_tarihi=fields.get("Karar Tarihi", ""),
                    yayimlanma_tarihi=fields.get("Yayımlanma Tarihi", ""),
                    karar_turu=fields.get("Karar Türü", ""),
                    konu=" ".join(link.text_content().split()),
                )
            )
        return rows, int(total_match.group(1))

    def fetch_pdf(self, karar_id: str) -> bytes:
        data = self._get(f"/Karar?kararId={karar_id}")
        if not data.startswith(b"%PDF-"):
            raise RekabetError(f"Karar dosyası PDF değil: {karar_id}")
        return data

    @staticmethod
    def pdf_url(karar_id: str) -> str:
        return f"{BASE_URL}/Karar?kararId={karar_id}"
