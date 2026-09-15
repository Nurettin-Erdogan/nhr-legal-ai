from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from time import sleep
from typing import Any, Callable

from ingestion.kdk.models import KdkDecision
from ingestion.kdk.parser import decision_from_row
from ingestion.kdk.portal import BASE_URL, KdkPortalClient, KdkPortalError, search_form
from ingestion.kdk.store import upsert_decision
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest
from worker.windows import month_window, next_month_start


class KdkSourceAdapter:
    source_name = "kdk"
    authority = "Kamu Denetçiliği Kurumu"
    active = True
    official_source_url = BASE_URL

    def __init__(self, *, client: KdkPortalClient | None = None) -> None:
        self.client = client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def _client(self) -> KdkPortalClient:
        settings = self._settings()
        return self.client or KdkPortalClient(
            max_retries=settings.max_retries,
            retry_backoff_seconds=max(1.0, settings.kdk_delay_seconds),
        )

    def health_check(self) -> AdapterHealth:
        client = self.client or KdkPortalClient(timeout_seconds=20, max_retries=1)
        try:
            client.begin_search()
            today = date.today()
            page = client.search_page(
                search_form(start=0, length=1, date_from=today, date_to=today)
            )
            if page.records_total < 0:
                return AdapterHealth(self.source_name, "degraded", "recordsTotal geçersiz")
            return AdapterHealth(
                self.source_name,
                "healthy",
                "KDK resmî arama ve PDF indirme sözleşmesi doğrulandı",
            )
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc))

    def validate(self, record: KdkDecision) -> list[str]:
        missing = []
        if not record.external_id.startswith("kdk:"):
            missing.append("external_id")
        for field_name in ("decision_no", "decision_type", "title", "raw_text", "source_url"):
            if not getattr(record, field_name):
                missing.append(field_name)
        if record.decision_date is None:
            missing.append("decision_date")
        return missing

    def dedup_identity(self, record: KdkDecision) -> str:
        return record.external_id

    def version_identity(self, record: KdkDecision) -> str:
        return f"sha256:{record.content_hash}"

    def provenance(self, record: KdkDecision) -> dict[str, Any]:
        return {
            "source_type": "other",
            "authority": self.authority,
            "canonical_source_name": "KDK Kararlar Bilgi Bankası",
            "official_source_url": record.source_url,
            "external_id": record.external_id,
            "source_document_id": record.metadata.get("source_document_id"),
            "ingestion_method": "kdk_public_datatables_pdf",
            "fetched_at": record.fetched_at.isoformat() if record.fetched_at else None,
            "decision_date": record.decision_date.isoformat(),
            "content_hash": record.content_hash,
            "source_version": self.version_identity(record),
        }

    def resolve_window(self, request: SyncRequest, cursor: dict[str, Any]) -> tuple[date, date]:
        if request.date_from and request.date_to:
            return request.date_from, request.date_to
        if cursor.get("window_from") and cursor.get("window_to") and not cursor.get("window_complete"):
            return date.fromisoformat(cursor["window_from"]), date.fromisoformat(cursor["window_to"])
        start = request.date_from or (
            date.fromisoformat(cursor["next_window_start"])
            if cursor.get("next_window_start")
            else self._settings().kdk_corpus_start
        )
        return month_window(start)

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        client = self._client()
        window_from, window_to = self.resolve_window(request, cursor)
        offset = int(cursor.get("offset") or 0) if request.resume else 0
        keyword = request.keyword.strip() or str(cursor.get("keyword") or "")
        max_records = request.max_records or settings.kdk_max_records
        page_size = min(20, max_records)
        client.begin_search(keyword)

        processed = seen = stored = duplicate = failed = 0
        expected: int | None = None
        window_complete = False
        halted_on_failure = False
        while processed < max_records and not should_stop():
            request_length = min(page_size, max_records - processed)
            page = client.search_page(
                search_form(
                    start=offset,
                    length=request_length,
                    keyword=keyword,
                    date_from=window_from,
                    date_to=window_to,
                )
            )
            expected = page.records_filtered
            if not page.rows:
                window_complete = True
                break
            for row in page.rows:
                if processed >= max_records or should_stop():
                    break
                processed += 1
                seen += 1
                record_id = str(row.get("id") or "").strip()
                extra = {
                    "offset": offset,
                    "window_from": window_from.isoformat(),
                    "window_to": window_to.isoformat(),
                    "expected_count": expected,
                    "requests_made": 1,
                }
                try:
                    publication_path = str(row.get("karaR_YAYIN_URL") or "").strip()
                    raw_date = str(row.get("karaR_TARIH") or "").strip()
                    if settings.kdk_delay_seconds:
                        sleep(settings.kdk_delay_seconds)
                    pdf, source_url = client.download_pdf(publication_path, raw_date)
                    extra["requests_made"] = 2
                    decision = decision_from_row(row, pdf, source_url=source_url)
                    missing = self.validate(decision)
                    if missing:
                        failed += 1
                        yield "quarantined", {
                            **extra,
                            "external_id": decision.external_id,
                            "reason": "missing_fields:" + ",".join(missing),
                            "raw": {"record_id": record_id, "missing": missing},
                        }
                        halted_on_failure = True
                        break
                    if dry_run:
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
                    offset += 1
                except KdkPortalError as exc:
                    failed += 1
                    yield "failed", {
                        **extra,
                        "external_id": f"kdk:{record_id}" if record_id else None,
                        "reason": str(exc),
                    }
                    halted_on_failure = True
                    break
            if halted_on_failure:
                break
            if offset >= (expected or 0) or len(page.rows) < request_length:
                window_complete = True
                break

        if should_stop():
            window_complete = False
        next_start = next_month_start(window_from) if window_complete else window_from
        self.last_cursor = {
            "offset": 0 if window_complete else offset,
            "page": 1 + (offset // page_size) if page_size else 1,
            "window_from": window_from.isoformat(),
            "window_to": window_to.isoformat(),
            "window_complete": window_complete,
            "next_window_start": next_start.isoformat(),
            "keyword": keyword,
            "expected_count": expected,
            "seen_count": seen,
            "stored_count": stored,
            "duplicate_count": duplicate,
            "failed_count": failed,
            "chamber": "",
        }
