"""AYM Kararlar Bilgi Bankası public arama JSON istemcisi.

Tam karar indirme akışı resmî istemcide güvenlik doğrulaması ister. Bu modül
doğrulamayı taklit etmez veya aşmaz; yalnız doğrulanmış public arama sözleşmesini
uygular.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.text import html_to_text

BASE_URL = "https://kararlarbilgibankasi.anayasa.gov.tr/"
SEARCH_PATH = "api/core/public/search"


class AymPortalError(RuntimeError):
    """AYM public portalı kullanılamayan veya beklenmeyen yanıt döndürdü."""


class AymSecurityVerificationRequired(AymPortalError):
    """Tam karar için etkileşimli/güvenlik doğrulaması gerektiğini bildirir."""


def parse_portal_date(value: Any) -> date | None:
    text = str(value or "").strip().split("T", 1)[0]
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def application_external_id(application_no: str) -> str:
    normalized = application_no.strip()
    if not normalized:
        raise ValueError("AYM başvuru numarası boş olamaz")
    return f"aym:bb:{normalized}"


def decision_url(application_no: str, *, base_url: str = BASE_URL) -> str:
    normalized = application_no.strip()
    if not normalized:
        raise ValueError("AYM başvuru numarası boş olamaz")
    return urljoin(base_url.rstrip("/") + "/", f"kbb/BB/{quote(normalized, safe='/')}")


@dataclass(frozen=True, slots=True)
class AymDecisionRow:
    official_id: str
    decision_type: str
    application_no: str
    applicant_name: str
    decision_date: date | None
    application_date: date | None
    publication_date: date | None
    chamber: str
    outcome: str
    subject: str
    confidential: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AymDecisionRow:
        subject_value = str(value.get("kararKonusu") or "")
        return cls(
            official_id=str(value.get("id") or "").strip(),
            decision_type=str(value.get("kararTipi") or "").strip(),
            application_no=str(value.get("basvuruNo") or "").strip(),
            applicant_name=str(value.get("basvuruAdi") or "").strip(),
            decision_date=parse_portal_date(value.get("kararTarihi")),
            application_date=parse_portal_date(value.get("basvuruTarihi")),
            publication_date=parse_portal_date(value.get("yayinTarihi")),
            chamber=str(value.get("kararVerenBirimLabel") or "").strip(),
            outcome=str(value.get("kararTuruBasvuruSonucuLabel") or "").strip(),
            subject=html_to_text(subject_value),
            confidential=bool(value.get("gizlilik", False)),
        )

    @property
    def external_id(self) -> str:
        return application_external_id(self.application_no)

    @property
    def source_url(self) -> str:
        return decision_url(self.application_no)


@dataclass(frozen=True, slots=True)
class SearchPage:
    rows: tuple[AymDecisionRow, ...]
    total: int
    page: int
    page_size: int


class AymPortalClient:
    """Resmî AYM arayüzünün kullandığı anahtarsız public arama istemcisi."""

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

    def _request(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        url = urljoin(self.base_url, SEARCH_PATH)
        data = json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Origin": self.base_url.rstrip("/"),
            "Referer": urljoin(self.base_url, "kbb/"),
            "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
        }

        for attempt in range(1, self.max_retries + 1):
            request = Request(url, data=data, headers=headers, method="POST")
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    raw = response.read()
                break
            except HTTPError as exc:
                if not is_retryable_status(exc.code) or attempt == self.max_retries:
                    raise AymPortalError(f"AYM HTTP hatası: {exc.code} ({url})") from exc
                time.sleep(
                    retry_wait_seconds(
                        attempt,
                        base_seconds=self.retry_backoff_seconds,
                        retry_after=exc.headers.get("Retry-After") if exc.headers else None,
                    )
                )
            except URLError as exc:
                if attempt == self.max_retries:
                    raise AymPortalError(f"AYM bağlantı hatası ({url}): {exc.reason}") from exc
                time.sleep(
                    retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds)
                )
        else:
            raise AssertionError("unreachable")

        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AymPortalError("AYM arama ucu JSON olmayan yanıt döndürdü") from exc
        if not isinstance(parsed, Mapping):
            raise AymPortalError("AYM arama ucu JSON nesnesi döndürmedi")
        return parsed

    def search_page(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        application_no: str | None = None,
        keyword: str | None = None,
    ) -> SearchPage:
        if page < 1:
            raise ValueError("AYM sayfa numarası en az 1 olmalıdır")
        if not 1 <= page_size <= 100:
            raise ValueError("AYM sayfa boyutu 1 ile 100 arasında olmalıdır")
        body: dict[str, Any] = {
            "kararTipi": "BireyselBasvuru",
            "page": page,
            "size": page_size,
            "sort": "yayinTarihi",
            "order": "desc",
        }
        if application_no:
            body["basvuruNo"] = application_no.strip()
        if keyword:
            body["query"] = keyword.strip()

        payload = self._request(body)
        data = payload.get("data")
        if not isinstance(data, list):
            raise AymPortalError("AYM arama yanıtında data listesi bulunamadı")
        rows = tuple(
            AymDecisionRow.from_mapping(item)
            for item in data
            if isinstance(item, Mapping)
        )
        if any(not row.official_id or not row.application_no for row in rows):
            raise AymPortalError("AYM arama sonucunda resmî id veya başvuru no eksik")
        try:
            total = int(payload.get("total") or 0)
            response_page = int(payload.get("page") or page)
            response_size = int(payload.get("page_size") or page_size)
        except (TypeError, ValueError) as exc:
            raise AymPortalError("AYM arama sayfalama metadata'sı geçersiz") from exc
        return SearchPage(rows=rows, total=total, page=response_page, page_size=response_size)

    def fetch_full_text(self, _row: AymDecisionRow) -> str:
        raise AymSecurityVerificationRequired(
            "AYM tam karar indirme akışı güvenlik doğrulaması istiyor; "
            "otomatik bypass uygulanmadı"
        )
