from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from time import sleep
from typing import Any, Callable

from ingestion.raw_capture import save_raw_response
from ingestion.yargitay.models import CourtDecision
from ingestion.yargitay.portal import (
    BASE_URL,
    CaptchaRequiredError,
    PortalError,
    YargitayPortalClient,
    portal_external_id,
)
from ingestion.yargitay.scraper import (
    ScraperConfig,
    YargitayScraper,
    _search_filters,
    decision_from_portal_row,
)
from ingestion.yargitay.store import upsert_decision
from worker.config import get_worker_settings
from worker.known_sources import skippable_external_ids, skipped_existing
from worker.lanes import advance_window_start, resolve_sync_window
from worker.models import AdapterHealth, RecordOutcome, SyncRequest
from worker.reconciliation import coverage_cursor, window_may_advance

logger = logging.getLogger("worker.yargitay")


class YargitaySourceAdapter:
    source_name = "yargitay"
    authority = "Yargıtay"
    active = True
    official_source_url = BASE_URL

    def __init__(self, *, client: YargitayPortalClient | None = None) -> None:
        self.client = client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def health_check(self) -> AdapterHealth:
        client = self.client or YargitayPortalClient(
            timeout_seconds=20,
            max_retries=1,
        )
        try:
            client._request("")
            today = date.today()
            filters = {
                "arananKelime": "",
                "birimYrgKurulDaire": "",
                "birimYrgHukukDaire": "",
                "birimYrgCezaDaire": "",
                "esasYil": "",
                "esasIlkSiraNo": "",
                "esasSonSiraNo": "",
                "kararYil": "",
                "kararIlkSiraNo": "",
                "kararSonSiraNo": "",
                "baslangicTarihi": today.replace(day=1).strftime("%d.%m.%Y"),
                "bitisTarihi": today.strftime("%d.%m.%Y"),
                "siralama": 3,
                "siralamaDirection": "desc",
                "pageSize": 1,
                "pageNumber": 1,
            }
            client.begin_detailed_search(filters)
            page = client.search_page(filters)
            if page.records_total < 0:
                return AdapterHealth(
                    self.source_name,
                    "degraded",
                    "recordsTotal beklenen JSON alanı yok veya geçersiz",
                )
            return AdapterHealth(
                self.source_name,
                "healthy",
                "karararama.yargitay.gov.tr JSON sözleşmesi doğrulandı",
            )
        except CaptchaRequiredError as exc:
            return AdapterHealth(self.source_name, "blocked", str(exc))
        except PortalError as exc:
            return AdapterHealth(self.source_name, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc))

    def validate(self, record: CourtDecision) -> list[str]:
        missing: list[str] = []
        if not record.external_id.startswith("yargitay:"):
            missing.append("external_id")
        if not record.court_name:
            missing.append("court_name")
        if not record.docket_no:
            missing.append("docket_no")
        if not record.decision_no:
            missing.append("decision_no")
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
        document_id = record.metadata.get("source_document_id")
        return {
            "source_type": "court_decision",
            "authority": self.authority,
            "canonical_source_name": "Yargıtay Karar Arama",
            "official_source_url": record.source_url or self.official_source_url,
            "external_id": record.external_id,
            "source_document_id": document_id,
            "transport_source": BASE_URL,
            "canonical_legal_source": "Yargıtay",
            "ingestion_method": "yargitay_public_json_http",
            "fetched_at": record.scraped_at.isoformat() if record.scraped_at else None,
            "decision_date": record.decision_date.isoformat() if record.decision_date else None,
            "content_hash": record.content_hash,
            "source_version": self.version_identity(record),
        }

    def resolve_window(
        self,
        request: SyncRequest,
        cursor: dict[str, Any],
    ) -> tuple[date, date]:
        try:
            settings = self._settings()
            corpus_start = settings.yargitay_corpus_start
            lookback_days = settings.current_lookback_days
        except RuntimeError:
            corpus_start = date(2000, 1, 1)
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
        window_from, window_to = self.resolve_window(request, cursor)
        start_page = int(cursor.get("page") or 1) if request.resume else 1
        row_offset = int(cursor.get("row_offset") or 0) if request.resume else 0
        if request.resume and cursor.get("window_from") and "row_offset" not in cursor:
            # Older checkpoints used a variable pageSize. Their page number
            # cannot safely identify a position with the fixed-size contract.
            logger.warning("legacy Yargıtay cursor; restarting window from page 1")
            start_page = 1
            row_offset = 0
        settings = self._settings()
        max_records = request.max_records or settings.yargitay_max_records
        keyword = request.keyword.strip() or str(cursor.get("keyword") or "")
        chamber = request.chamber.strip() or str(cursor.get("chamber") or "")
        config = ScraperConfig(
            keyword=keyword,
            chamber=chamber,
            decision_date_from=window_from,
            decision_date_to=window_to,
            max_decisions=max_records,
            output_dir=Path(settings.snapshot_dir) / "yargitay",
            delay_seconds=settings.yargitay_delay_seconds,
            max_retries=settings.max_retries,
            start_page=start_page,
        )
        scraper = YargitayScraper(config, client=self.client)
        page_number = start_page
        processed = 0
        seen_in_window = 0
        stored_in_window = 0
        duplicate_in_window = 0
        failed_in_window = 0
        quarantined_in_window = 0
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

        # pageSize must stay fixed across runs: page + row_offset is the resume key.
        first_filters = _search_filters(config, page_number=page_number, page_size=config.page_size)
        scraper.client.begin_detailed_search(first_filters)

        while processed < max_records and not should_stop():
            page_size = config.page_size
            filters = _search_filters(config, page_number=page_number, page_size=page_size)
            page = scraper.client.search_page(filters)
            expected = page.records_filtered
            if not page.rows:
                if (page_number - 1) * page_size < expected:
                    raise PortalError(
                        f"Yargıtay {page_number}. sayfa boş, ancak portal {expected} sonuç bildiriyor"
                    )
                break
            remaining_rows = page.rows[row_offset:]
            known = skippable_external_ids(
                connection,
                [
                    portal_external_id(row.document_id)
                    for row in remaining_rows
                    if row.document_id
                ],
                lane=request.lane,
            )
            for row_index, row in enumerate(remaining_rows, start=row_offset):
                if should_stop() or processed >= max_records:
                    break
                processed += 1
                seen_in_window += 1
                extra = {
                    "page": page_number,
                    "window_from": window_from.isoformat(),
                    "window_to": window_to.isoformat(),
                    "expected_count": expected,
                    "requests_made": 1,
                }
                try:
                    external_id = (
                        portal_external_id(row.document_id) if row.document_id else ""
                    )
                    if external_id and external_id in known:
                        duplicate_in_window += 1
                        yield "unchanged", skipped_existing(extra, external_id)
                        row_offset = row_index + 1
                        continue
                    if settings.yargitay_delay_seconds:
                        sleep(settings.yargitay_delay_seconds)
                    html = scraper.client.fetch_document_html(row.document_id)
                    extra["requests_made"] = 2
                    save_raw_response(
                        root=settings.snapshot_dir,
                        source="yargitay",
                        record_id=row.document_id,
                        url=scraper.client.base_url + f"getDokuman?id={row.document_id}",
                        method="POST",
                        body=html.encode("utf-8", errors="replace"),
                        request={"id": row.document_id, "window_from": window_from.isoformat()},
                    )
                    decision = decision_from_portal_row(row, html, base_url=scraper.client.base_url)
                    missing = self.validate(decision)
                    if missing:
                        yield "quarantined", {
                            **extra,
                            "external_id": decision.external_id,
                            "reason_code": "missing_fields",
                            "reason": "missing_fields:" + ",".join(missing),
                            "raw": {"document_id": row.document_id, "missing": missing},
                        }
                        quarantined_in_window += 1
                        row_offset = row_index + 1
                        continue
                    scraper.archive.save(decision)
                    if dry_run:
                        yield "created", {**extra, "external_id": decision.external_id, "dry_run": True}
                        stored_in_window += 1
                        row_offset = row_index + 1
                        continue
                    result = upsert_decision(connection, decision)
                    outcome: RecordOutcome = result.status  # type: ignore[assignment]
                    if outcome == "unchanged":
                        duplicate_in_window += 1
                    else:
                        stored_in_window += 1
                    yield outcome, {
                        **extra,
                        "external_id": result.external_id,
                        "legal_source_id": result.legal_source_id,
                    }
                    row_offset = row_index + 1
                except CaptchaRequiredError:
                    raise
                except PortalError as exc:
                    failed_in_window += 1
                    yield "failed", {
                        **extra,
                        "external_id": f"yargitay:{row.document_id}" if row.document_id else None,
                        "reason": str(exc),
                    }
                    break
            if row_offset < len(page.rows):
                break
            if expected is not None and page_number * page_size >= expected:
                break
            page_number += 1
            row_offset = 0

        coverage = coverage_cursor(
            expected=expected,
            seen=prior_seen + seen_in_window,
            stored=prior_stored + stored_in_window,
            duplicate=prior_dup + duplicate_in_window,
            quarantined=prior_q + quarantined_in_window,
            failed=failed_in_window,
        )
        window_complete = window_may_advance(
            reconciled=bool(coverage["reconciled"]),
            processed=processed,
            failed=failed_in_window,
            already_started=prior_seen > 0 or start_page > 1 or int(cursor.get("row_offset") or 0) > 0,
            stopped=should_stop(),
        )

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
            "keyword": keyword,
            "chamber": chamber,
            "window_seen_total": 0 if window_complete else prior_seen + seen_in_window,
            "window_stored_total": 0 if window_complete else prior_stored + stored_in_window,
            "window_duplicate_total": 0 if window_complete else prior_dup + duplicate_in_window,
            "window_quarantined_total": 0 if window_complete else prior_q + quarantined_in_window,
            **coverage,
            "window_complete": window_complete,
        }
