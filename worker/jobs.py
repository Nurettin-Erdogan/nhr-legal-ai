from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

import psycopg

from ingestion.yargitay.portal import CaptchaRequiredError
from worker import ACTIVE_SOURCES
from worker.adapters import get_adapter
from worker.checkpoints import CheckpointStore
from worker.config import get_worker_settings
from worker.lanes import CURRENT_LANE_SOURCES, checkpoint_name
from worker.locks import JobLockedError, source_job_lock
from worker.models import RunCounters, SyncRequest
from worker.repository import SyncRepository


def _should_stop_never() -> bool:
    return False


def _carry_backfill_horizon(
    previous: dict[str, Any], current: dict[str, Any], lane: str
) -> dict[str, Any]:
    """Keep the verified start marker when a page adapter replaces its cursor."""
    if lane == "backfill":
        for key in ("full_horizon_start", "horizon_audit_version"):
            if key in previous:
                current[key] = previous[key]
    return current


_CURSOR_POSITION_KEYS = (
    "next_window_start",
    "page",
    "row_offset",
    "offset",
    "type_index",
    "catalog_page",
    "catalog_offset",
    "last_article_no",
    "law_no",
    "window_from",
    "window_to",
)


def _cursor_advanced(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """True when the adapter wrote a different resume cursor, including KDK offset."""
    return dict(previous or {}) != dict(current or {})


def _quarantined_progress(
    previous: dict[str, Any], current: dict[str, Any], *, failed: int, quarantined: int
) -> bool:
    """A skipped bad record need not put a progressing source on error cooldown."""
    if failed or not quarantined:
        return False
    return any(
        previous.get(key) != current.get(key) for key in _CURSOR_POSITION_KEYS
    )


def _interval_for(
    source_name: str,
    *,
    cursor: dict[str, Any] | None = None,
    status: str = "success",
    today: date | None = None,
    lane: str = "backfill",
) -> timedelta:
    settings = get_worker_settings()
    if lane == "current":
        regular = settings.current_interval_minutes
        retry = settings.current_retry_interval_minutes
        if status != "success" or not cursor:
            return timedelta(minutes=regular)
        complete = cursor.get("window_complete", cursor.get("complete"))
        if complete is False:
            return timedelta(minutes=retry)
        next_start = cursor.get("next_window_start")
        window_from = cursor.get("window_from")
        # Lookback içindeki sonraki aya geç: kısa aralık. Ufka sarılınca uzun aralık.
        if (
            complete is True
            and isinstance(next_start, str)
            and isinstance(window_from, str)
            and date.fromisoformat(next_start) > date.fromisoformat(window_from)
        ):
            return timedelta(minutes=retry)
        return timedelta(minutes=regular)
    regular_minutes = {
        "yargitay": settings.yargitay_interval_minutes,
        "danistay": settings.danistay_interval_minutes,
        "mevzuat": settings.mevzuat_interval_minutes,
        "kdk": settings.kdk_interval_minutes,
        "aym": settings.aym_interval_minutes,
    }[source_name]
    if status != "success" or not cursor:
        return timedelta(minutes=regular_minutes)
    backfill_minutes = {
        "yargitay": settings.yargitay_backfill_interval_minutes,
        "danistay": settings.danistay_backfill_interval_minutes,
        "mevzuat": settings.mevzuat_backfill_interval_minutes,
        "kdk": settings.kdk_backfill_interval_minutes,
        "aym": settings.aym_backfill_interval_minutes,
    }[source_name]
    complete = cursor.get("window_complete", cursor.get("complete"))
    has_more = complete is False
    next_start = cursor.get("next_window_start")
    if complete is True and isinstance(next_start, str):
        has_more = date.fromisoformat(next_start) <= (today or datetime.now(UTC).date())
    return timedelta(minutes=backfill_minutes if has_more else regular_minutes)


def run_sync(
    connection: psycopg.Connection,
    request: SyncRequest,
    *,
    should_stop: Callable[[], bool] = _should_stop_never,
    adapter: Any | None = None,
) -> dict[str, Any]:
    source = request.source.strip().lower()
    lane = request.lane if request.lane in {"backfill", "current"} else "backfill"
    if lane == "current" and source not in CURRENT_LANE_SOURCES:
        return {
            "source": source,
            "lane": lane,
            "status": "failed",
            "error": f"{source} current şeridine sahip değil",
        }
    adapter = adapter or get_adapter(source)
    if source not in ACTIVE_SOURCES:
        health = adapter.health_check()
        return {
            "source": source,
            "lane": lane,
            "status": "failed",
            "error": health.detail,
            "health": health.state,
        }

    job_key = checkpoint_name(source, lane)
    repo = SyncRepository(connection)
    store = CheckpointStore(repo)
    targeted_law = source == "mevzuat" and bool(request.law_no.strip())
    try:
        lock = source_job_lock(connection, source)
        lock.__enter__()
    except JobLockedError as exc:
        return {"source": source, "lane": lane, "status": "failed", "error": str(exc)}

    try:
        checkpoint = store.load(job_key)
        previous_cursor = dict(checkpoint.last_cursor or {})
        original_checkpoint = checkpoint if targeted_law else None
        if targeted_law:
            checkpoint = deepcopy(checkpoint)
        counters = RunCounters()
        run = repo.start_run(
            job_key,
            checkpoint_before=checkpoint.as_json(),
            metadata={"dry_run": request.dry_run, "resume": request.resume, "lane": lane},
        )
        checkpoint.last_attempt_at = datetime.now(UTC)
        status = "success"
        error: str | None = None
        last_external_id = checkpoint.last_external_id

        try:
            events = adapter.sync(
                request,
                cursor=checkpoint.last_cursor if request.resume and not targeted_law else {},
                connection=connection,
                dry_run=request.dry_run,
                should_stop=should_stop,
            )
            for outcome, payload in events:
                if outcome == "quarantined" and not request.dry_run:
                    repo.quarantine(
                        source,
                        external_id=payload.get("external_id"),
                        reason_code=str(payload.get("reason_code") or "missing_fields"),
                        reason=str(payload.get("reason") or "invalid"),
                        raw_payload=payload.get("raw") or payload,
                    )
                counters.add(outcome)
                if outcome in {"failed", "invalid"} and not error:
                    error = str(payload.get("reason") or "record_failed")
                counters.requests_made += int(payload.get("requests_made") or 0)
                if payload.get("external_id"):
                    last_external_id = str(payload["external_id"])
                if should_stop():
                    status = "cancelled"
                    error = "shutdown"
                    break
            cursor = _carry_backfill_horizon(
                checkpoint.last_cursor,
                dict(getattr(adapter, "last_cursor", {}) or {}),
                lane,
            )
            if cursor.get("window_from"):
                checkpoint.last_date_from = date.fromisoformat(cursor["window_from"])
                checkpoint.last_date_to = date.fromisoformat(cursor["window_to"])
                checkpoint.last_page = int(cursor.get("page") or 1)
                # Her run'ın delta sayaçlarını yaz; SQL tarafı kümülatif toplar.
                # Pencere birden fazla run'da bitiyorsa son run önceki coverage'ı ezmez.
                if not request.dry_run:
                    repo.upsert_coverage(
                        source,
                        checkpoint.last_date_from,
                        checkpoint.last_date_to,
                        chamber=str(cursor.get("chamber") or ""),
                        expected_count=cursor.get("expected_count"),
                        seen_count=int(cursor.get("seen_count") or 0),
                        stored_count=int(cursor.get("stored_count") or 0),
                        duplicate_count=int(cursor.get("duplicate_count") or 0),
                        failed_count=int(cursor.get("failed_count") or 0),
                        complete=bool(cursor.get("reconciled")) and lane != "current",
                    )
            checkpoint.last_cursor = cursor
            checkpoint.last_external_id = last_external_id
            if should_stop() and status != "cancelled":
                status = "cancelled"
                error = "shutdown"
            elif counters.records_failed or counters.records_quarantined:
                status = "partial" if status != "cancelled" else status
        except CaptchaRequiredError as exc:
            status = "captcha_required"
            error = str(exc)
            checkpoint.health_state = "blocked"
            checkpoint.health_detail = error
            checkpoint.last_cursor["page"] = checkpoint.last_page
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = str(exc)
            checkpoint.health_state = "failed"
            checkpoint.health_detail = error

        if status == "success" and not request.dry_run:
            checkpoint.last_successful_sync_at = datetime.now(UTC)
            checkpoint.consecutive_failures = 0
            checkpoint.last_error = None
            checkpoint.health_state = "healthy"
            checkpoint.health_detail = None
        elif status == "partial" and not request.dry_run:
            # partial: son başarılı sync damgasını güncelleme.
            checkpoint.consecutive_failures = 0
            checkpoint.last_error = error
            if checkpoint.health_state != "blocked":
                quarantine_progress = _quarantined_progress(
                    previous_cursor, checkpoint.last_cursor,
                    failed=counters.records_failed,
                    quarantined=counters.records_quarantined,
                )
                checkpoint.health_state = "healthy" if quarantine_progress else "degraded"
                checkpoint.health_detail = error
        elif status in {"failed", "captcha_required", "cancelled"}:
            checkpoint.consecutive_failures += 1
            checkpoint.last_error = error
            if status == "captcha_required":
                checkpoint.health_state = "blocked"
            elif status == "failed":
                checkpoint.health_state = "failed"

        if targeted_law:
            # A one-law import must not replace the catalog cursor or
            # postpone its next scheduled pass. The run itself is still logged.
            assert original_checkpoint is not None
            checkpoint = original_checkpoint
        else:
            interval_status = status
            if status == "partial" and _cursor_advanced(
                previous_cursor, checkpoint.last_cursor
            ):
                # A batch cap or a few bad rows is not a portal outage. Keep
                # the short backfill cadence so the collector does not idle
                # for hours between 40–80 record runs.
                interval_status = "success"
            checkpoint.next_run_at = datetime.now(UTC) + _interval_for(
                source, cursor=checkpoint.last_cursor, status=interval_status, lane=lane
            )
            if not request.dry_run:
                store.save(checkpoint)
        repo.finish_run(
            run,
            status=status,
            counters=counters,
            last_error=error,
            checkpoint_after=checkpoint.as_json(),
            metadata={
                "dry_run": request.dry_run,
                "targeted_law": request.law_no or None,
                "lane": lane,
            },
        )
        return {
            "source": source,
            "lane": lane,
            "job": job_key,
            "status": status,
            "run_id": str(run.id),
            "counters": counters.as_json(),
            "error": error,
            "checkpoint": checkpoint.as_json(),
        }
    finally:
        lock.__exit__(None, None, None)


def run_many(
    connection: psycopg.Connection,
    sources: list[str],
    request_kwargs: dict[str, Any],
    *,
    should_stop: Callable[[], bool] = _should_stop_never,
) -> list[dict[str, Any]]:
    results = []
    for source in sources:
        if should_stop():
            break
        request = SyncRequest(source=source, **request_kwargs)
        results.append(run_sync(connection, request, should_stop=should_stop))
    return results
