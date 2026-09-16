from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from time import sleep
from typing import Any, Callable

from ingestion.danistay.portal import (
    BASE_URL,
    DanistayPortalClient,
    DanistayPortalError,
)
from ingestion.danistay.scraper import ScraperConfig, decision_from_portal_row, search_filters
from ingestion.raw_capture import save_raw_response
from ingestion.yargitay.archive import DecisionArchive
from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.portal import CaptchaRequiredError
from ingestion.yargitay.store import upsert_decision
from worker.config import get_worker_settings
from worker.lanes import advance_window_start, resolve_sync_window
from worker.models import AdapterHealth, RecordOutcome, SyncRequest
from worker.reconciliation import coverage_cursor


class DanistaySourceAdapter:
    source_name = "danistay"
    authority = "Danıştay"
    active = True
    official_source_url = BASE_URL

    def __init__(self, *, client: DanistayPortalClient | None = None) -> None:
        self.client = client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def _client(self) -> DanistayPortalClient:
        settings = self._settings()
        return self.client or DanistayPortalClient(
            max_retries=settings.max_retries,
            retry_backoff_seconds=max(1.0, settings.danistay_delay_seconds),
        )

    def health_check(self) -> AdapterHealth:
        client = self.client or DanistayPortalClient(timeout_seconds=20, max_retries=1)
        try:
            filters = search_filters(
                ScraperConfig(
                    decision_date_from=date(2025, 1, 1),
                    decision_date_to=date(2025, 1, 1),
                ),
                page_number=1,
                page_size=1,
            )
            client.begin_detailed_search(filters)
            page = client.search_page(filters)
            if page.records_total < 0:
                return AdapterHealth(self.source_name, "degraded", "recordsTotal geçersiz")
            return AdapterHealth(
                self.source_name,
                "healthy",
                "karararama.danistay.gov.tr arama ve oturum sözleşmesi doğrulandı",
            )
        except CaptchaRequiredError as exc:
            return AdapterHealth(self.source_name, "blocked", str(exc))
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc))

    def validate(self, record: CourtDecision) -> list[str]:
        missing: list[str] = []
        if not record.external_id.startswith("danistay:"):
            missing.append("external_id")
        for field_name in ("court_name", "docket_no", "decision_no"):
            if not getattr(record, field_name):
                missing.append(field_name)
        if not record.chamber:
            missing.append("chamber")
        if record.decision_date is None:
            missing.append("decision_date")
        if not record.raw_text.strip():
            missing.append("raw_text")
        return missing

    def dedup_identity(self, record: CourtDecision) -> str:
        return record.external_id

    def version_identity(self, record: CourtDecision) -> str:
        return f"sha256:{record.content_hash}"

    def provenance(self, record: CourtDecision) -> dict[str, Any]:
        return {
            "source_type": "court_decision",
            "authority": self.authority,
            "canonical_source_name": "Danıştay Karar Arama",
            "official_source_url": record.source_url or self.official_source_url,
            "external_id": record.external_id,
            "source_document_id": record.metadata.get("source_document_id"),
            "transport_source": BASE_URL,
            "canonical_legal_source": "Danıştay",
            "ingestion_method": "danistay_public_json_http",
            "fetched_at": record.scraped_at.isoformat() if record.scraped_at else None,
            "decision_date": record.decision_date.isoformat() if record.decision_date else None,
            "content_hash": record.content_hash,
            "source_version": self.version_identity(record),
        }

    def resolve_window(self, request: SyncRequest, cursor: dict[str, Any]) -> tuple[date, date]:
        try:
            settings = self._settings()
            corpus_start = settings.danistay_corpus_start
            lookback_days = settings.current_lookback_days
        except RuntimeError:
            corpus_start = date(1982, 1, 1)
            lookback_days = 45
        return resolve_sync_window(
            request,
            cursor,
            corpus_start=corpus_start,
            lookback_days=lookback_days,
        )

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        if request.keyword.strip():
            raise ValueError(
                "Danıştay detaylı arama ucu serbest kelime filtresi sunmuyor; "
                "bu adapter'da --keyword kullanılamaz"
            )
        settings = self._settings()
        client = self._client()
        window_from, window_to = self.resolve_window(request, cursor)
        page_number = int(cursor.get("page") or 1) if request.resume else 1
        row_offset = int(cursor.get("row_offset") or 0) if request.resume else 0
        max_records = request.max_records or settings.danistay_max_records
        config = ScraperConfig(
            keyword=request.keyword.strip() or str(cursor.get("keyword") or ""),
            chamber=request.chamber.strip(),
            decision_date_from=window_from,
            decision_date_to=window_to,
            max_decisions=max_records,
            output_dir=Path(settings.snapshot_dir) / "danistay",
            delay_seconds=settings.danistay_delay_seconds,
            max_retries=settings.max_retries,
            start_page=page_number,
        )
        archive = DecisionArchive(config.output_dir)
        initial = search_filters(config, page_number=page_number, page_size=config.page_size)
        client.begin_detailed_search(initial)

        processed = seen = stored = duplicate = failed = quarantined = 0
        expected: int | None = None
        window_complete = False
        halted_on_failure = False
        same_window = (
            request.resume
            and cursor.get("window_from") == window_from.isoformat()
            and cursor.get("window_to") == window_to.isoformat()
        )
        prior_seen = int(cursor.get("window_seen_total") or 0) if same_window else 0
        prior_stored = int(cursor.get("window_stored_total") or 0) if same_window else 0
        prior_dup = int(cursor.get("window_duplicate_total") or 0) if same_window else 0
        prior_q = int(cursor.get("window_quarantined_total") or 0) if same_window else 0
        expected: int | None = None
        window_complete = False
        halted_on_failure = False
        while processed < max_records and not should_stop():
            remaining = max_records - processed
            page_size = config.page_size
            page = client.search_page(search_filters(config, page_number=page_number, page_size=page_size))
            expected = page.records_filtered
            if not page.rows:
                if (page_number - 1) * page_size < expected:
                    raise DanistayPortalError(
                        f"Danıştay {page_number}. sayfa boş, ancak portal {expected} sonuç bildiriyor"
                    )
                break
            for row_index, row in enumerate(page.rows[row_offset:], start=row_offset):
                if should_stop():
                    break
                if processed >= max_records:
                    break
                processed += 1
                seen += 1
                extra = {
                    "page": page_number,
                    "window_from": window_from.isoformat(),
                    "window_to": window_to.isoformat(),
                    "expected_count": expected,
                    "requests_made": 1,
                }
                try:
                    if settings.danistay_delay_seconds:
                        sleep(settings.danistay_delay_seconds)
                    html = client.fetch_document_html(row.document_id, keyword=row.keyword)
                    extra["requests_made"] = 2
                    save_raw_response(
                        root=settings.snapshot_dir,
                        source="danistay",
                        record_id=row.document_id,
                        url=client.base_url + f"getDokuman?id={row.document_id}",
                        method="GET",
                        body=html.encode("utf-8", errors="replace"),
                        request={"id": row.document_id},
                    )
                    decision = decision_from_portal_row(row, html, base_url=client.base_url)
                    missing = self.validate(decision)
                    if missing:
                        quarantined += 1
                        yield "quarantined", {
                            **extra,
                            "external_id": decision.external_id,
                            "reason_code": "missing_fields",
                            "reason": "missing_fields:" + ",".join(missing),
                            "raw": {"document_id": row.document_id, "missing": missing},
                        }
                        row_offset = row_index + 1
                        continue
                    archive.save(decision)
                    if dry_run:
                        stored += 1
                        yield "created", {**extra, "external_id": decision.external_id, "dry_run": True}
                        row_offset = row_index + 1
                        continue
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
                except CaptchaRequiredError:
                    raise
                except DanistayPortalError as exc:
                    failed += 1
                    yield "failed", {
                        **extra,
                        "external_id": f"danistay:{row.document_id}" if row.document_id else None,
                        "reason": str(exc),
                    }
                    halted_on_failure = True
                    break
            if halted_on_failure:
                break
            if row_offset < len(page.rows):
                # Tur sayfanın ortasında bitti; aynı sayfadaki sonraki
                # kayıttan devam et ve değişen pageSize ile kayıt atlama.
                break
            if expected and page_number * page_size >= expected:
                break
            page_number += 1
            row_offset = 0

        coverage = coverage_cursor(
            expected=expected,
            seen=prior_seen + seen,
            stored=prior_stored + stored,
            duplicate=prior_dup + duplicate,
            quarantined=prior_q + quarantined,
            failed=failed,
        )
        window_complete = bool(coverage["reconciled"]) and not should_stop()
        next_start = advance_window_start(
            window_from,
            window_complete,
            request,
            lookback_days=self._settings().current_lookback_days,
        )
        self.last_cursor = {
            "page": 1 if window_complete else page_number,
            "row_offset": 0 if window_complete else row_offset,
            "window_from": window_from.isoformat(),
            "window_to": window_to.isoformat(),
            "next_window_start": next_start.isoformat(),
            "keyword": config.keyword,
            "chamber": config.chamber,
            "window_seen_total": 0 if window_complete else prior_seen + seen,
            "window_stored_total": 0 if window_complete else prior_stored + stored,
            "window_duplicate_total": 0 if window_complete else prior_dup + duplicate,
            "window_quarantined_total": 0 if window_complete else prior_q + quarantined,
            **coverage,
            "window_complete": window_complete,
        }
