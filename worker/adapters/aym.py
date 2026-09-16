from __future__ import annotations

from collections.abc import Iterator
from time import sleep
from typing import Any, Callable

from ingestion.aym.parser import decision_from_udf
from ingestion.aym.portal import (
    BASE_URL,
    AymFullTextUnavailable,
    AymPortalClient,
    AymPortalError,
)
from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.store import upsert_decision
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class AymSourceAdapter:
    source_name = "aym"
    authority = "Anayasa Mahkemesi"
    active = True
    official_source_url = BASE_URL

    def __init__(self, *, client: AymPortalClient | None = None) -> None:
        self.client = client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def _client(self) -> AymPortalClient:
        settings = self._settings()
        return self.client or AymPortalClient(
            max_retries=settings.max_retries,
            retry_backoff_seconds=max(1.0, settings.aym_delay_seconds),
        )

    def health_check(self) -> AdapterHealth:
        client = self.client or AymPortalClient(timeout_seconds=20, max_retries=1)
        try:
            page = client.search_page(page=1, page_size=1)
            if not page.rows:
                return AdapterHealth(self.source_name, "degraded", "AYM araması boş döndü")
            client.list_decision_files(page.rows[0])
            return AdapterHealth(
                self.source_name,
                "healthy",
                "AYM public arama, karar dosyası listesi ve UDF akışı doğrulandı",
            )
        except AymFullTextUnavailable as exc:
            return AdapterHealth(self.source_name, "degraded", str(exc))
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc))

    def validate(self, record: CourtDecision) -> list[str]:
        missing = []
        if not record.external_id.startswith("aym:bb:"):
            missing.append("external_id")
        for field_name in ("court_name", "docket_no", "title", "raw_text", "source_url"):
            if not getattr(record, field_name):
                missing.append(field_name)
        if record.decision_date is None:
            missing.append("decision_date")
        return missing

    def dedup_identity(self, record: CourtDecision) -> str:
        return record.external_id

    def version_identity(self, record: CourtDecision) -> str:
        return f"sha256:{record.content_hash}"

    def provenance(self, record: CourtDecision) -> dict[str, Any]:
        return {
            "source_type": "court_decision",
            "authority": self.authority,
            "canonical_source_name": "Anayasa Mahkemesi Kararlar Bilgi Bankası",
            "official_source_url": record.source_url,
            "external_id": record.external_id,
            "source_document_id": record.metadata.get("source_document_id"),
            "ingestion_method": "aym_public_json_udf",
            "fetched_at": record.scraped_at.isoformat() if record.scraped_at else None,
            "decision_date": record.decision_date.isoformat() if record.decision_date else None,
            "content_hash": record.content_hash,
            "source_version": self.version_identity(record),
        }

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        if request.date_from or request.date_to:
            raise ValueError(
                "AYM public arama sözleşmesinde tarih filtresi henüz doğrulanmadı; "
                "--date-from/--date-to kullanılamaz"
            )
        settings = self._settings()
        client = self._client()
        # A completed one-off application search must not pin future corpus
        # runs to the same application number forever.
        resume_cursor = cursor if request.resume and not cursor.get("complete") else {}
        page_number = int(resume_cursor.get("page") or 1)
        row_offset = int(resume_cursor.get("row_offset") or 0)
        keyword = request.keyword.strip() or str(resume_cursor.get("keyword") or "")
        max_records = request.max_records or settings.aym_max_records
        page_size = 20
        application_no = keyword if keyword.replace("/", "").isdigit() and "/" in keyword else None

        processed = seen = stored = duplicate = failed = 0
        expected: int | None = None
        window_complete = False
        halted_on_failure = False
        while processed < max_records and not should_stop():
            page = client.search_page(
                page=page_number,
                page_size=page_size,
                application_no=application_no,
                keyword=None if application_no else keyword or None,
            )
            expected = page.total
            if not page.rows:
                window_complete = True
                break
            for row_index, row in enumerate(page.rows[row_offset:], start=row_offset):
                if processed >= max_records or should_stop():
                    break
                processed += 1
                seen += 1
                extra = {
                    "page": page_number,
                    "expected_count": expected,
                    "requests_made": 1,
                }
                try:
                    files = client.list_decision_files(row)
                    if settings.aym_delay_seconds:
                        sleep(settings.aym_delay_seconds)
                    udf, download_url = client.download_udf(files[0])
                    extra["requests_made"] = 3
                    decision = decision_from_udf(row, udf, download_url=download_url)
                    missing = self.validate(decision)
                    if missing:
                        failed += 1
                        yield "quarantined", {
                            **extra,
                            "external_id": row.external_id,
                            "reason_code": "missing_fields",
                            "reason": "missing_fields:" + ",".join(missing),
                            "raw": {"official_id": row.official_id, "missing": missing},
                        }
                    elif dry_run:
                        stored += 1
                        yield "created", {**extra, "external_id": decision.external_id, "dry_run": True}
                    else:
                        result = upsert_decision(connection, decision)
                        outcome: RecordOutcome = result.status  # type: ignore[assignment]
                        if outcome == "unchanged":
                            duplicate += 1
                        else:
                            stored += 1
                        yield outcome, {
                            **extra,
                            "external_id": result.external_id,
                            "legal_source_id": result.legal_source_id,
                        }
                    row_offset = row_index + 1
                except AymFullTextUnavailable as exc:
                    failed += 1
                    yield "quarantined", {
                        **extra,
                        "external_id": row.external_id,
                        "reason_code": "full_text_unavailable",
                        "reason": "full_text_unavailable:" + str(exc),
                        "raw": {"official_id": row.official_id},
                    }
                    row_offset = row_index + 1
                except AymPortalError as exc:
                    failed += 1
                    yield "failed", {
                        **extra,
                        "external_id": row.external_id,
                        "reason": str(exc),
                    }
                    halted_on_failure = True
                    break
            if halted_on_failure:
                break
            if row_offset < len(page.rows):
                break
            if page_number * page_size >= (expected or 0):
                window_complete = True
                break
            page_number += 1
            row_offset = 0

        self.last_cursor = {
            "page": 1 if window_complete else page_number,
            "row_offset": 0 if window_complete else row_offset,
            "complete": window_complete,
            "keyword": keyword,
            "expected_count": expected,
            "seen_count": seen,
            "stored_count": stored,
            "duplicate_count": duplicate,
            "failed_count": failed,
        }
