"""AYM Kararlar Bilgi Bankası public arama ve UDF karar istemcisi.

PDF üretim ucu güvenlik doğrulaması ister ve kullanılmaz. Tam metin, portalın
kendi istemcisinin de doğrulama olmadan kullandığı public UDF attachment
ucundan alınır.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, build_opener

from ingestion.http import is_retryable_status, retry_wait_seconds
from ingestion.text import html_to_text

BASE_URL = "https://kararlarbilgibankasi.anayasa.gov.tr/"
SEARCH_PATH = "api/core/public/search"


class AymPortalError(RuntimeError):
    """AYM public portalı kullanılamayan veya beklenmeyen yanıt döndürdü."""


class AymSecurityVerificationRequired(AymPortalError):
    """Tam karar için etkileşimli/güvenlik doğrulaması gerektiğini bildirir."""


class AymFullTextUnavailable(AymPortalError):
    """Yayımlanmış kaydın public UDF tam metni henüz yok."""


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


def decision_url(official_id: str, *, base_url: str = BASE_URL) -> str:
    normalized = official_id.strip()
    if not normalized:
        raise ValueError("AYM resmî karar kimliği boş olamaz")
    encoded = base64.b64encode(f"kbb:{normalized}".encode("utf-8")).decode("ascii")
    return urljoin(
        base_url.rstrip("/") + "/",
        "kbb/pages/search/BireyselBasvuru?"
        f"id={quote(encoded, safe='')}&type=BireyselBasvuru",
    )


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
        return decision_url(self.official_id)


@dataclass(frozen=True, slots=True)
class AymDecisionFile:
    file_id: str
    decision_id: str
    folder: str
    filename: str
    source_kind: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AymDecisionFile:
        raw_url = str(value.get("url") or "").strip()
        parsed = urlparse(raw_url)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            files_index = parts.index("files")
            folder, filename = parts[files_index + 1 : files_index + 3]
        except (ValueError, IndexError) as exc:
            raise AymPortalError("AYM UDF dosya yolu beklenen yapıda değil") from exc
        if not filename.lower().endswith(".udf"):
            raise AymPortalError("AYM karar dosyası UDF formatında değil")
        if folder != "bireysel-basvuru" or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
            raise AymPortalError("AYM UDF dosya yolu güvenli değil")
        return cls(
            file_id=str(value.get("id") or "").strip(),
            decision_id=str(value.get("kararId") or "").strip(),
            folder=folder,
            filename=filename,
            source_kind=str(value.get("kaynak") or "").strip(),
        )


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

    def _open(self, request: Request) -> bytes:
        url = request.full_url
        if urlparse(url).hostname != urlparse(self.base_url).hostname:
            raise AymPortalError("AYM isteği resmî alan adına ait değil")
        for attempt in range(1, self.max_retries + 1):
            try:
                with self.opener.open(request, timeout=self.timeout_seconds) as response:
                    return response.read()
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
                time.sleep(retry_wait_seconds(attempt, base_seconds=self.retry_backoff_seconds))
        raise AssertionError("unreachable")

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

        request = Request(url, data=data, headers=headers, method="POST")
        raw = self._open(request)

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

    def list_decision_files(self, row: AymDecisionRow) -> tuple[AymDecisionFile, ...]:
        path = (
            f"api/core/public/kararlar/{quote(row.official_id)}/dosyalar?"
            f"kararTipi={quote(row.decision_type)}"
        )
        url = urljoin(self.base_url, path)
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "Referer": urljoin(self.base_url, "kbb/"),
                "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
            },
        )
        try:
            payload = json.loads(self._open(request).decode("utf-8-sig"))
            data = payload["data"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise AymPortalError("AYM karar dosyaları yanıtı geçersiz") from exc
        if not isinstance(data, list):
            raise AymPortalError("AYM karar dosyaları listesi bulunamadı")
        files = tuple(
            AymDecisionFile.from_mapping(value)
            for value in data
            if isinstance(value, Mapping)
            and str(value.get("url") or "").lower().endswith(".udf")
        )
        if not files:
            raise AymFullTextUnavailable("AYM kararı için public UDF tam metni bulunamadı")
        return files

    def download_udf(self, decision_file: AymDecisionFile) -> tuple[bytes, str]:
        path = (
            "api/core/public/files/download-attachment/"
            f"{quote(decision_file.folder, safe='')}/{quote(decision_file.filename, safe='')}"
        )
        url = urljoin(self.base_url, path)
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "Referer": urljoin(self.base_url, "kbb/"),
                "User-Agent": "nhr-legal-ai/0.1 (official-public-source-ingestion)",
            },
        )
        raw = self._open(request)
        if not raw.startswith(b"PK"):
            raise AymPortalError("AYM public UDF yanıtı geçerli ZIP arşivi değil")
        return raw, url

    def fetch_full_text(self, _row: AymDecisionRow) -> str:
        raise AymSecurityVerificationRequired(
            "AYM PDF üretim akışı güvenlik doğrulaması istiyor; "
            "public UDF akışı kullanılmalıdır"
        )
