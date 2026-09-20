from __future__ import annotations

from collections.abc import Iterator
from time import sleep
from typing import Any, Callable

from ingestion.source_errors import should_retry_same_record
from ingestion.aym.parser import decision_from_file
from ingestion.aym.portal import (
    BASE_URL,
    AymFullTextUnavailable,
    AymPortalClient,
    AymPortalError,
)
from ingestion.corpus_bounds import AYM_DECISION_TYPES
from ingestion.raw_capture import save_raw_response
from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.store import upsert_decision
from worker.config import get_worker_settings
from worker.known_sources import skippable_external_ids, skipped_existing
from worker.models import AdapterHealth, RecordOutcome, SyncRequest
from worker.reconciliation import coverage_cursor, window_may_advance


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
        if not record.external_id.startswith("aym:"):
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
        resume_cursor = cursor if request.resume and not cursor.get("complete") else {}
        keyword = request.keyword.strip() or str(resume_cursor.get("keyword") or "")
        max_records = request.max_records or settings.aym_max_records
        application_no = keyword if keyword.replace("/", "").isdigit() and "/" in keyword else None
        types = (
            ("BireyselBasvuru",)
            if application_no or keyword
            else AYM_DECISION_TYPES
        )
        type_index = int(resume_cursor.get("type_index") or 0)
        if type_index >= len(types):
            type_index = 0
        page_number = int(resume_cursor.get("page") or 1)
        row_offset = int(resume_cursor.get("row_offset") or 0)
        same_partition = request.resume and int(resume_cursor.get("type_index") or 0) == type_index
        configured_page_size = max(1, min(100, settings.aym_page_size))
        page_size = configured_page_size
        if same_partition:
            stored_size = resume_cursor.get("page_size")
            if stored_size:
                page_size = max(1, min(100, int(stored_size)))
            elif (
                int(resume_cursor.get("page") or 1) > 1
                or int(resume_cursor.get("row_offset") or 0)
                or int(resume_cursor.get("window_seen_total") or 0)
            ):
                page_size = 20
        prior_seen = int(resume_cursor.get("window_seen_total") or 0) if same_partition else 0
        prior_stored = int(resume_cursor.get("window_stored_total") or 0) if same_partition else 0
        prior_dup = int(resume_cursor.get("window_duplicate_total") or 0) if same_partition else 0
        prior_q = int(resume_cursor.get("window_quarantined_total") or 0) if same_partition else 0
        processed = seen = stored = duplicate = failed = quarantined = 0
        expected: int | None = None

        def _reset_partition_counters() -> None:
            nonlocal prior_seen, prior_stored, prior_dup, prior_q
            nonlocal seen, stored, duplicate, failed, quarantined
            prior_seen = prior_stored = prior_dup = prior_q = 0
            seen = stored = duplicate = failed = quarantined = 0

        while processed < max_records and not should_stop() and type_index < len(types):
            karar_tipi = types[type_index]
            try:
                page = client.search_page(
                    page=page_number,
                    page_size=page_size,
                    application_no=application_no,
                    keyword=None if application_no else keyword or None,
                    karar_tipi=karar_tipi,
                )
            except AymPortalError as exc:
                if should_retry_same_record(exc):
                    failed += 1
                    yield "failed", {
                        "external_id": None,
                        "reason": str(exc),
                        "page": page_number,
                        "karar_tipi": karar_tipi,
                        "requests_made": 1,
                    }
                    break
                raise
            expected = page.total
            if not page.rows:
                coverage = coverage_cursor(
                    expected=expected,
                    seen=prior_seen + seen,
                    stored=prior_stored + stored,
                    duplicate=prior_dup + duplicate,
                    quarantined=prior_q + quarantined,
                    failed=failed,
                )
                if expected == 0 or window_may_advance(
                    reconciled=bool(coverage["reconciled"]),
                    processed=0,
                    failed=failed,
                    already_started=prior_seen + seen > 0 or page_number > 1 or row_offset > 0,
                    stopped=should_stop(),
                ):
                    type_index += 1
                    page_number, row_offset = 1, 0
                    page_size = configured_page_size
                    if type_index >= len(types):
                        break
                    _reset_partition_counters()
                    continue
                break
            remaining_rows = page.rows[row_offset:]
            known_ids: list[str] = []
            for row in remaining_rows:
                try:
                    known_ids.append(row.external_id)
                except ValueError:
                    continue
            known = skippable_external_ids(connection, known_ids, lane=request.lane)
            for row_index, row in enumerate(remaining_rows, start=row_offset):
                if processed >= max_records or should_stop():
                    break
                processed += 1
                seen += 1
                extra = {
                    "page": page_number,
                    "expected_count": expected,
                    "requests_made": 1,
                    "karar_tipi": karar_tipi,
                }
                try:
                    try:
                        external_id = row.external_id
                    except ValueError:
                        external_id = ""
                    if external_id and external_id in known:
                        duplicate += 1
                        yield "unchanged", skipped_existing(extra, external_id)
                        row_offset = row_index + 1
                        continue
                    files = client.list_decision_files(row)
                    if settings.aym_delay_seconds:
                        sleep(settings.aym_delay_seconds)
                    raw, download_url = client.download_udf(files[0])
                    extra["requests_made"] = 3
                    save_raw_response(
                        root=settings.snapshot_dir,
                        source="aym",
                        record_id=row.official_id,
                        url=download_url,
                        method="GET",
                        body=raw,
                        request={"kararTipi": karar_tipi, "official_id": row.official_id},
                    )
                    decision = decision_from_file(
                        row,
                        raw,
                        download_url=download_url,
                        filename=files[0].filename,
                    )
                    missing = self.validate(decision)
                    if missing:
                        quarantined += 1
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
                except (AymFullTextUnavailable, AymPortalError) as exc:
                    if isinstance(exc, AymPortalError) and should_retry_same_record(exc):
                        failed += 1
                        try:
                            failed_id = row.external_id
                        except ValueError:
                            failed_id = str(row.official_id)
                        yield "failed", {
                            **extra,
                            "external_id": failed_id,
                            "reason": str(exc),
                        }
                        break
                    quarantined += 1
                    reason_code = (
                        "full_text_unavailable"
                        if isinstance(exc, AymFullTextUnavailable)
                        else "unverified_or_unreadable"
                    )
                    yield "quarantined", {
                        **extra,
                        "external_id": row.external_id,
                        "reason_code": reason_code,
                        "reason": reason_code + ":" + str(exc),
                        "raw": {
                            "official_id": row.official_id,
                            "karar_tipi": karar_tipi,
                        },
                    }
                    row_offset = row_index + 1
            if row_offset < len(page.rows):
                break
            if page_number * page_size >= (expected or 0):
                coverage = coverage_cursor(
                    expected=expected,
                    seen=prior_seen + seen,
                    stored=prior_stored + stored,
                    duplicate=prior_dup + duplicate,
                    quarantined=prior_q + quarantined,
                    failed=failed,
                )
                if coverage["reconciled"] or window_may_advance(
                    reconciled=bool(coverage["reconciled"]),
                    processed=0,
                    failed=failed,
                    already_started=prior_seen + seen > 0 or page_number > 1,
                    stopped=should_stop(),
                ):
                    type_index += 1
                    page_number, row_offset = 1, 0
                    page_size = configured_page_size
                    if type_index >= len(types):
                        break
                    _reset_partition_counters()
                    continue
                break
            page_number += 1
            row_offset = 0

        all_done = type_index >= len(types) and not should_stop()
        coverage = coverage_cursor(
            expected=expected,
            seen=prior_seen + seen,
            stored=prior_stored + stored,
            duplicate=prior_dup + duplicate,
            quarantined=prior_q + quarantined,
            failed=failed,
        )
        self.last_cursor = {
            "page": 1 if all_done else page_number,
            "row_offset": 0 if all_done else row_offset,
            "type_index": min(type_index, max(0, len(types) - 1)),
            "karar_tipi": types[min(type_index, len(types) - 1)],
            "partitions": list(types),
            "complete": all_done,
            "keyword": "" if all_done else keyword,
            "page_size": page_size,
            "window_seen_total": 0 if all_done else prior_seen + seen,
            "window_stored_total": 0 if all_done else prior_stored + stored,
            "window_duplicate_total": 0 if all_done else prior_dup + duplicate,
            "window_quarantined_total": 0 if all_done else prior_q + quarantined,
            **coverage,
            "reconciled": all_done or bool(coverage["reconciled"]),
            "window_complete": all_done,
        }
