"""Mevzuat Bilgi Sistemi'nin resmî public arama akışıyla künye doğrulama.

Site arayüzünün yayımladığı ``GenelArama`` JavaScript'i
``POST /anasayfa/MevzuatDatatable`` isteğini kullanır. Bu istemci yalnız bu
gözlemlenmiş sözleşmeyi ve sonuçtaki resmî detay sayfasını kullanır; tahminî
bir API yolu üretmez.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.text import html_to_text, normalize_text, tr_casefold

BASE_URL = "https://www.mevzuat.gov.tr/"
SEARCH_PATH = "anasayfa/MevzuatDatatable"
_ALLOWED_HOSTS = {"mevzuat.gov.tr", "www.mevzuat.gov.tr"}


class MbsError(RuntimeError):
    """MBS yanıtı erişilemez veya doğrulanmış sözleşmeye uymuyor."""


@dataclass(frozen=True, slots=True)
class MbsDocument:
    law_no: str
    law_name: str
    legislation_type: int
    series: str
    acceptance_date: date | None
    official_gazette_date: date | None
    official_gazette_no: str | None
    detail_url: str
    pdf_url: str
    doc_url: str


@dataclass(frozen=True, slots=True)
class MbsVerification:
    verified: bool
    law_no: str
    law_name: str
    detail_url: str | None
    pdf_url: str | None
    doc_url: str | None
    requested_gazette_date: str | None
    observed_gazette_date: str | None
    requested_gazette_no: str | None
    observed_gazette_no: str | None
    title_matches: bool
    verified_at: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip().split("T", 1)[0]
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def _official_url(value: Any, *, base_url: str, expected_path: str | None = None) -> str:
    url = urljoin(base_url, str(value or "").strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise MbsError("MBS resmî olmayan bir URL döndürdü")
    if expected_path and not parsed.path.casefold().startswith(expected_path.casefold()):
        raise MbsError("MBS beklenmeyen bir resmî URL yolu döndürdü")
    return url


class _DocumentLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


class MbsClient:
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
                    raise MbsError(f"MBS HTTP hatası: {exc.code} ({url})") from exc
                time.sleep(
                    retry_wait_seconds(
                        attempt,
                        base_seconds=self.retry_backoff_seconds,
                        retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                    )
                )
            except URLError as exc:
                if attempt == self.max_retries:
                    raise MbsError(f"MBS bağlantı hatası: {exc.reason}") from exc
                time.sleep(retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds))
        raise AssertionError("unreachable")

    def search_law(self, law_no: str) -> MbsDocument:
        encoded = base64.b64encode(law_no.strip().encode("utf-8")).decode("ascii")
        body = {
            "draw": 1,
            "start": 0,
            "length": 25,
            "parameters": {
                "AranacakIfade": encoded,
                "AranacakYer": "Baslik",
                "TamCumle": False,
                "MevzuatTur": 0,
                "GenelArama": True,
            },
        }
        raw = self._request(urljoin(self.base_url, SEARCH_PATH), body=body)
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MbsError("MBS arama ucu JSON olmayan yanıt döndürdü") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise MbsError("MBS arama yanıtı beklenen sözleşmede değil")
        exact = [
            item
            for item in payload["data"]
            if isinstance(item, Mapping) and str(item.get("mevzuatNo") or "").strip() == law_no.strip()
        ]
        if len(exact) > 1:
            # Aynı numarayı farklı türler paylaşabilir (ör. 6736 hem Kanun hem CB Kararı);
            # korpus şu an yalnız kanun aldığından tür=1 (Kanunlar) ile daraltılır.
            exact = [item for item in exact if int(item.get("mevzuatTur") or 0) == 1]
        if len(exact) != 1:
            raise MbsError(f"{law_no} numaralı mevzuat için tekil MBS kaydı bulunamadı")
        item = exact[0]
        detail_url = _official_url(item.get("url"), base_url=self.base_url, expected_path="/mevzuat")
        detail_html = self._request(detail_url).decode("utf-8", errors="replace")
        parser = _DocumentLinkParser()
        parser.feed(detail_html)
        pdf_links = [
            _official_url(link, base_url=self.base_url, expected_path="/MevzuatMetin/")
            for link in parser.links
            if urlparse(urljoin(self.base_url, link)).path.casefold().endswith(".pdf")
        ]
        doc_links = [
            _official_url(link, base_url=self.base_url, expected_path="/MevzuatMetin/")
            for link in parser.links
            if urlparse(urljoin(self.base_url, link)).path.casefold().endswith(".doc")
        ]
        if len(pdf_links) != 1 or len(doc_links) != 1:
            raise MbsError("MBS detay sayfasında tekil resmî PDF/DOC bağlantısı bulunamadı")
        return MbsDocument(
            law_no=law_no.strip(),
            law_name=normalize_text(html_to_text(str(item.get("mevAdi") or ""))),
            legislation_type=int(item.get("mevzuatTur") or 0),
            series=str(item.get("mevzuatTertip") or "").strip(),
            acceptance_date=_parse_date(item.get("kabulTarih")),
            official_gazette_date=_parse_date(item.get("resmiGazeteTarihi")),
            official_gazette_no=str(item.get("resmiGazeteSayisi") or "").strip() or None,
            detail_url=detail_url,
            pdf_url=pdf_links[0],
            doc_url=doc_links[0],
        )

    def verify_legislation(
        self,
        *,
        law_no: str,
        law_name: str,
        publication_date: date | None,
        issue_no: str | None,
    ) -> MbsVerification:
        document = self.search_law(law_no)
        expected_title = tr_casefold(normalize_text(law_name))
        observed_title = tr_casefold(document.law_name)
        title_matches = bool(
            expected_title
            and observed_title
            and (expected_title in observed_title or observed_title in expected_title)
        )
        date_matches = publication_date is None or publication_date == document.official_gazette_date
        requested_issue = str(issue_no or "").strip() or None
        issue_matches = requested_issue is None or requested_issue == document.official_gazette_no
        verified = title_matches and date_matches and issue_matches
        reasons = []
        if not title_matches:
            reasons.append("mevzuat başlığı uyuşmuyor")
        if not date_matches:
            reasons.append(
                f"RG tarihi uyuşmuyor: beklenen={publication_date}, bulunan={document.official_gazette_date}"
            )
        if not issue_matches:
            reasons.append(
                f"RG sayısı uyuşmuyor: beklenen={requested_issue}, bulunan={document.official_gazette_no}"
            )
        return MbsVerification(
            verified=verified,
            law_no=document.law_no,
            law_name=document.law_name,
            detail_url=document.detail_url,
            pdf_url=document.pdf_url,
            doc_url=document.doc_url,
            requested_gazette_date=publication_date.isoformat() if publication_date else None,
            observed_gazette_date=(
                document.official_gazette_date.isoformat()
                if document.official_gazette_date
                else None
            ),
            requested_gazette_no=requested_issue,
            observed_gazette_no=document.official_gazette_no,
            title_matches=title_matches,
            verified_at=datetime.now(UTC).isoformat(),
            detail=(
                "MBS künye ve resmî konsolide metin bağlantıları doğrulandı"
                if verified
                else "; ".join(reasons)
            ),
        )
