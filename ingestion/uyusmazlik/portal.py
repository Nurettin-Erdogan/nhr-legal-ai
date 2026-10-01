"""Uyuşmazlık Mahkemesi karar arama uygulaması (kararlar.uyusmazlik.gov.tr) istemcisi.

Site eski tip ASP.NET WebForms'tur: liste `GridView1` postback ile sayfalanır, her karar
`Uploads/<esas>.pdf` olarak yayımlanır.

TLS: sitenin sertifikası (TÜBİTAK Kamu SM tarafından Uyuşmazlık Mahkemesi'ne verilmiş)
2026-09-18'de süresi dolmuş olarak bulundu. Doğrulamayı kapatmak yerine önce normal doğrulama
denenir (sertifika yenilenmişse geçer); yalnız "süresi dolmuş" hatasında, tam bu sertifikanın
SHA-256 parmak izi eşleşirse bağlantı kabul edilir. Farklı bir sertifika hiçbir zaman kabul edilmez.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import ssl
import time
import urllib.parse
from dataclasses import dataclass

import lxml.html

HOST = "kararlar.uyusmazlik.gov.tr"
BASE_URL = f"https://{HOST}/"
USER_AGENT = "nhr-legal-ai/0.1 (official-public-source-ingestion)"
# 2026-09-21'de görülen (süresi 2026-09-18'de dolmuş) resmî sertifikanın SHA-256 parmak izi.
EXPIRED_CERT_PIN = "EC30DDBA90CE312A056ADAD9B430D54A593BAB758EC2CA22B47B554D2964A0BF"


class UyusmazlikError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ListRow:
    esas_no: str
    karar_no: str
    karar_tarihi: str
    pdf_path: str


class UyusmazlikClient:
    def __init__(self, *, delay_seconds: float = 1.5, timeout_seconds: float = 60.0, max_retries: int = 3) -> None:
        self.delay = delay_seconds
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self._last = 0.0
        self._cookies: dict[str, str] = {}
        self._form: dict[str, str] = {}

    def _pace(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _connect(self) -> http.client.HTTPSConnection:
        connection = http.client.HTTPSConnection(HOST, timeout=self.timeout, context=ssl.create_default_context())
        try:
            connection.connect()
            return connection
        except ssl.SSLCertVerificationError as exc:
            connection.close()
            if "expired" not in str(exc).lower():
                raise UyusmazlikError(f"Uyuşmazlık sertifikası doğrulanamadı: {exc}") from exc
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(HOST, timeout=self.timeout, context=context)
        connection.connect()
        fingerprint = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest().upper()
        if fingerprint != EXPIRED_CERT_PIN:
            connection.close()
            raise UyusmazlikError(f"Uyuşmazlık sertifika parmak izi eşleşmiyor: {fingerprint}")
        return connection

    def _request(self, method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._pace()
            try:
                connection = self._connect()
                request_headers = {"User-Agent": USER_AGENT, "Connection": "close", **(headers or {})}
                if self._cookies:
                    request_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
                connection.request(method, path, body=body, headers=request_headers)
                response = connection.getresponse()
                data = response.read()
                for header, value in response.getheaders():
                    if header.lower() == "set-cookie":
                        name, _, rest = value.partition("=")
                        self._cookies[name.strip()] = rest.split(";", 1)[0]
                status = response.status
                connection.close()
                if status == 429:
                    raise UyusmazlikError("Uyuşmazlık HTTP 429; kaynak hız sınırı, beklenmeli")
                if status >= 400 and status not in {500, 502, 503, 504}:
                    raise UyusmazlikError(f"Uyuşmazlık HTTP {status}: {path}")
                if status < 400:
                    return data
                last = UyusmazlikError(f"HTTP {status}")
            except UyusmazlikError:
                raise
            except (OSError, http.client.HTTPException) as exc:
                last = exc
            time.sleep(min(30, 2**attempt))
        raise UyusmazlikError(f"Uyuşmazlık isteği başarısız: {last}")

    @staticmethod
    def _parse_page(html: str) -> tuple[dict[str, str], list[ListRow], int | None]:
        document = lxml.html.fromstring(html)
        form = {
            name: (document.xpath(f'string(//input[@name="{name}"]/@value)') or "")
            for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")
        }
        rows: list[ListRow] = []
        for tr in document.xpath('//table[@id="GridView1"]/tr[td]'):
            cells = tr.xpath("./td")
            link = tr.xpath('.//a[contains(@href,"Uploads/")]/@href')
            if len(cells) >= 3 and link:
                rows.append(
                    ListRow(
                        esas_no=cells[0].text_content().strip(),
                        karar_no=cells[1].text_content().strip(),
                        karar_tarihi=cells[2].text_content().strip(),
                        pdf_path=link[0].strip(),
                    )
                )
        current = document.xpath('string(//table[@id="GridView1"]//tr[last()]//span)').strip()
        return form, rows, int(current) if current.isdigit() else None

    def first_page(self) -> tuple[list[ListRow], int | None]:
        html = self._request("GET", "/").decode("utf-8", errors="replace")
        self._form, rows, current = self._parse_page(html)
        return rows, current

    def goto(self, argument: str) -> tuple[list[ListRow], int | None]:
        """`Page$<n>` / `Page$Last` postback'i; dönüş: (satırlar, güncel sayfa no)."""
        if not self._form.get("__VIEWSTATE"):
            raise UyusmazlikError("Önce first_page çağrılmalı")
        body = urllib.parse.urlencode({**self._form, "__EVENTTARGET": "GridView1", "__EVENTARGUMENT": argument, "txtSearch": ""})
        html = self._request(
            "POST",
            "/",
            body=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": BASE_URL},
        ).decode("utf-8", errors="replace")
        self._form, rows, current = self._parse_page(html)
        return rows, current

    def fetch_pdf(self, pdf_path: str) -> bytes:
        data = self._request("GET", "/" + pdf_path.lstrip("/"))
        if not data.startswith(b"%PDF-"):
            raise UyusmazlikError(f"Karar dosyası PDF değil: {pdf_path}")
        return data

    @staticmethod
    def pdf_url(pdf_path: str) -> str:
        return urllib.parse.urljoin(BASE_URL, pdf_path)


def slug(esas_no: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", esas_no).strip("-")
