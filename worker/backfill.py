"""Tek komutluk tarihsel backfill: checkpoint/resume, sonra incremental daemon."""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta
from time import sleep
from typing import Any, Callable

import psycopg

from ingestion.source_errors import is_rate_limited, should_retry_same_record
from worker import ACTIVE_SOURCES
from worker.config import get_worker_settings
from worker.jobs import _cursor_advanced, _interval_for, run_sync
from worker.lanes import CURRENT_LANE_SOURCES, checkpoint_name
from worker.models import SyncRequest
from worker.repository import SyncRepository
from worker.scheduler import run_daemon

logger = logging.getLogger("worker.backfill")

DATE_WINDOW_SOURCES = frozenset({"yargitay", "danistay", "kdk"})
HORIZON_AUDIT_VERSION = 1


def _captcha_blocked(checkpoint: Any) -> bool:
    blob = f"{getattr(checkpoint, 'last_error', '') or ''} {getattr(checkpoint, 'health_detail', '') or ''}"
    return getattr(checkpoint, "health_state", None) == "blocked" and "captcha" in blob.casefold()


def _source_retry_at(
    checkpoint: Any,
    source: str,
    retry_after: dict[str, datetime],
    now: datetime,
) -> datetime | None:
    """Earliest time this source may run again. None means due now.

    Failed/CAPTCHA checkpoints used to inherit the idle daemon interval
    (6–24h) or drop out of the loop entirely. Keep the process alive and
    retry on a short, capped cooldown instead of honoring that long wait.
    """
    settings = get_worker_settings()
    candidates: list[datetime] = []
    in_memory = retry_after.get(source)
    if in_memory is not None:
        candidates.append(in_memory)
    last = getattr(checkpoint, "last_attempt_at", None)
    error = str(getattr(checkpoint, "last_error", "") or "")
    if _captcha_blocked(checkpoint):
        minutes = settings.captcha_retry_minutes
    elif error and (is_rate_limited(error) or should_retry_same_record(error)):
        minutes = settings.rate_limit_retry_minutes
    elif getattr(checkpoint, "health_state", None) == "failed":
        minutes = settings.failure_retry_minutes
    else:
        minutes = None
    if minutes is not None and last is not None:
        candidates.append(last + timedelta(minutes=minutes))
    until = max(candidates) if candidates else None
    if until and until > now:
        return until
    return None


def _current_lookback_open(cursor: dict[str, Any]) -> bool:
    """True while the current lane still has months left in the lookback."""
    complete = cursor.get("window_complete", cursor.get("complete"))
    if complete is False:
        return True
    next_start = cursor.get("next_window_start")
    window_from = cursor.get("window_from")
    if complete is True and isinstance(next_start, str) and isinstance(window_from, str):
        return date.fromisoformat(next_start) > date.fromisoformat(window_from)
    return False


def _should_stop_never() -> bool:
    return False


def corpus_start_for(source: str, *, settings: Any | None = None) -> date:
    settings = settings or get_worker_settings()
    per_source = {
        "yargitay": settings.yargitay_corpus_start,
        "danistay": settings.danistay_corpus_start,
        "kdk": settings.kdk_corpus_start,
    }.get(source)
    if per_source is None:
        return settings.full_corpus_start
    return per_source


def is_historical_complete(
    source: str,
    cursor: dict[str, Any] | None,
    *,
    today: date | None = None,
) -> bool:
    cursor = cursor or {}
    today = today or datetime.now(UTC).date()
    if source in DATE_WINDOW_SOURCES:
        complete = cursor.get("window_complete")
        next_start = cursor.get("next_window_start")
        if complete is True and isinstance(next_start, str):
            return date.fromisoformat(next_start) > today and cursor.get("reconciled") is True
        return False
    return bool(cursor.get("complete")) and cursor.get("reconciled") is not False


def _cursor_progress_date(cursor: dict[str, Any]) -> date | None:
    for key in ("next_window_start", "window_from"):
        raw = cursor.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                return date.fromisoformat(raw.strip())
            except ValueError:
                continue
    return None


def apply_full_horizon(
    source: str,
    cursor: dict[str, Any] | None,
    *,
    horizon: date,
) -> dict[str, Any]:
    """Kaynağın doğrulanmış corpus_start değerine hizala.

    Ufuktan eski imleç ileri alınır. Yeni (daha eski) doğrulanmış taban
    `full_horizon_start` değişince uygulanır; taranmayan yıllar complete yazılmaz.
    """
    cursor = dict(cursor or {})
    if source == "mevzuat":
        if cursor.get("mode") == "discovery":
            return cursor
        migrated = {
            "mode": "discovery",
            "profile": "discovery",
            "type_index": 0,
            "catalog_page": 1,
            "catalog_offset": 0,
            "complete": False,
        }
        if cursor.get("law_no") and cursor.get("last_article_no"):
            migrated["law_no"] = cursor["law_no"]
            migrated["last_article_no"] = cursor["last_article_no"]
        return migrated
    if source not in DATE_WINDOW_SOURCES:
        return cursor
    mark = horizon.isoformat()
    progress = _cursor_progress_date(cursor)
    previous = str(cursor.get("full_horizon_start") or "")
    # A legacy cursor at 2020 does not prove that earlier published years were
    # scanned. Revisit the verified horizon once; upserts remain idempotent.
    if cursor.get("horizon_audit_version") != HORIZON_AUDIT_VERSION or (
        previous and previous > mark
    ):
        return {
            "full_horizon_start": mark,
            "horizon_audit_version": HORIZON_AUDIT_VERSION,
            "next_window_start": mark,
            "window_complete": True,
            "reconciled": False,
        }
    if progress is not None and progress >= horizon:
        kept = dict(cursor)
        kept["full_horizon_start"] = mark
        kept["horizon_audit_version"] = HORIZON_AUDIT_VERSION
        return kept
    return {
        "full_horizon_start": mark,
        "horizon_audit_version": HORIZON_AUDIT_VERSION,
        "next_window_start": mark,
        "window_complete": True,
        "reconciled": False,
    }


def prepare_full_backfill(connection: psycopg.Connection, source: str) -> dict[str, Any]:
    settings = get_worker_settings()
    repo = SyncRepository(connection)
    checkpoint = repo.get_checkpoint(source)
    horizon = corpus_start_for(source, settings=settings)
    rewritten = apply_full_horizon(source, checkpoint.last_cursor, horizon=horizon)
    if rewritten != (checkpoint.last_cursor or {}):
        checkpoint.last_cursor = rewritten
        checkpoint.next_run_at = datetime.now(UTC)
        repo.save_checkpoint(checkpoint)
        logger.info(
            "full backfill horizon prepared source=%s start=%s",
            source,
            horizon.isoformat(),
        )
    return rewritten


def embed_new_legal_chunks(connection: psycopg.Connection) -> dict[str, Any]:
    """Yeni legal_chunks satırlarını vektörler. Hata ingestion'ı geri almaz."""
    from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
    from ingestion.embeddings import embed_legal_chunks

    settings = get_worker_settings()
    try:
        provider = create_embedding_provider(
            provider_name=os.getenv("EMBEDDING_PROVIDER", "ollama"),
            model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "768")),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")),
        )
        summary = embed_legal_chunks(
            connection,
            provider,
            limit=settings.embed_limit_per_run,
            batch_size=settings.embed_batch_size,
            delay_seconds=settings.embed_delay_seconds,
            max_retries=settings.max_retries,
            retry_backoff_seconds=15,
        )
        logger.info(
            "embedding pass embedded=%s remaining=%s",
            summary.embedded,
            summary.remaining,
        )
        return {"embedded": summary.embedded, "remaining": summary.remaining}
    except (EmbeddingProviderError, Exception) as exc:  # noqa: BLE001
        logger.warning("embedding pass skipped: %s", exc)
        return {"embedded": 0, "remaining": None, "error": str(exc)}


def run_full_backfill(
    connection: psycopg.Connection,
    sources: list[str],
    *,
    should_stop: Callable[[], bool] = _should_stop_never,
    embed: bool = True,
    then_incremental: bool = True,
    pause_seconds: float | None = None,
    sync: Callable[..., dict[str, Any]] = run_sync,
    embed_fn: Callable[[psycopg.Connection], dict[str, Any]] | None = None,
    daemon: Callable[..., None] = run_daemon,
) -> dict[str, Any]:
    settings = get_worker_settings()
    pause = settings.backfill_pause_seconds if pause_seconds is None else pause_seconds
    embed_fn = embed_fn or embed_new_legal_chunks
    sources = [item.strip().lower() for item in sources]
    for source in sources:
        if source not in ACTIVE_SOURCES:
            raise ValueError(f"Backfill yalnız ACTIVE kaynaklar için: {source}")
        prepare_full_backfill(connection, source)

    keep_alive = not then_incremental
    completed: list[str] = []
    blocked: list[str] = []
    runs: list[dict[str, Any]] = []
    remaining = [source for source in sources if source not in completed]
    repo = SyncRepository(connection)
    retry_after: dict[str, datetime] = {}
    lanes: dict[str, str] = {source: "backfill" for source in remaining}

    for source in list(remaining):
        archive_cursor = repo.get_checkpoint(source).last_cursor
        if not is_historical_complete(source, archive_cursor):
            continue
        if source not in completed:
            completed.append(source)
        if keep_alive and source in CURRENT_LANE_SOURCES:
            lanes[source] = "current"
            logger.info(
                "full backfill already complete source=%s; staying alive on current lane",
                source,
            )
        elif not keep_alive:
            remaining.remove(source)
            logger.info("full backfill complete source=%s", source)

    while remaining and not should_stop():
        progressed = False
        earliest_retry: datetime | None = None
        for source in list(remaining):
            if should_stop():
                break
            archive_checkpoint = repo.get_checkpoint(source)
            if (
                keep_alive
                and source in CURRENT_LANE_SOURCES
                and is_historical_complete(source, archive_checkpoint.last_cursor)
            ):
                lanes[source] = "current"
                if source not in completed:
                    completed.append(source)
            lane = lanes[source]
            checkpoint = (
                repo.get_checkpoint(checkpoint_name(source, lane))
                if lane == "current"
                else archive_checkpoint
            )
            now = datetime.now(UTC)
            gate = archive_checkpoint if _captcha_blocked(archive_checkpoint) else checkpoint
            if _captcha_blocked(gate) and source not in blocked:
                blocked.append(source)
                logger.warning(
                    "full backfill captcha source=%s; process stays, retry after cooldown",
                    source,
                )
            deferred_until = _source_retry_at(gate, source, retry_after, now)
            if deferred_until is not None:
                earliest_retry = min(earliest_retry or deferred_until, deferred_until)
                continue
            logger.info("full backfill starting source=%s lane=%s", source, lane)
            before_cursor = dict(checkpoint.last_cursor or {})
            result = sync(
                connection,
                SyncRequest(source=source, lane=lane, resume=True),
                should_stop=should_stop,
            )
            runs.append(result)
            progressed = True
            status = result.get("status")
            cursor = (result.get("checkpoint") or {}).get("last_cursor") or {}
            if embed and status not in {"failed", "captcha_required"}:
                result["embedding"] = embed_fn(connection)
            if status == "captcha_required":
                if source not in blocked:
                    blocked.append(source)
                delay = _interval_for(source, cursor=cursor, status="captcha_required")
                retry_after[source] = datetime.now(UTC) + delay
                logger.warning(
                    "full backfill captcha source=%s retry_at=%s",
                    source,
                    retry_after[source].isoformat(),
                )
                continue
            if lane == "backfill" and is_historical_complete(source, cursor):
                if source not in completed:
                    completed.append(source)
                if keep_alive and source in CURRENT_LANE_SOURCES:
                    lanes[source] = "current"
                    logger.info(
                        "full backfill complete source=%s; staying alive on current lane",
                        source,
                    )
                    continue
                if keep_alive:
                    delay = _interval_for(source, cursor=cursor, status="success")
                    retry_after[source] = datetime.now(UTC) + delay
                    logger.info(
                        "full backfill complete source=%s; rescan at %s",
                        source,
                        retry_after[source].isoformat(),
                    )
                    continue
                remaining.remove(source)
                logger.info("full backfill complete source=%s", source)
                continue
            error = str(result.get("error") or "")
            if status == "failed" and "zaten çalışıyor" in error:
                retry_after[source] = datetime.now(UTC) + timedelta(seconds=3)
                logger.warning(
                    "full backfill waiting for lock source=%s until=%s",
                    source, retry_after[source].isoformat(),
                )
            elif error and is_rate_limited(error):
                delay = _interval_for(
                    source, cursor=cursor, status="failed", lane=lane, error=error
                )
                retry_after[source] = datetime.now(UTC) + delay
                logger.warning(
                    "full backfill rate-limited source=%s until=%s",
                    source, retry_after[source].isoformat(),
                )
            elif status in {"failed", "cancelled"} or (
                lane == "backfill" and not _cursor_advanced(before_cursor, cursor)
            ):
                delay = _interval_for(
                    source, cursor=cursor,
                    status="failed",
                    lane=lane,
                )
                retry_after[source] = datetime.now(UTC) + delay
                logger.warning(
                    "full backfill deferred source=%s status=%s until=%s",
                    source, status, retry_after[source].isoformat(),
                )
            elif lane == "current" and (
                not _current_lookback_open(cursor)
                or not _cursor_advanced(before_cursor, cursor)
            ):
                delay = _interval_for(
                    source, cursor=cursor, status="success", lane="current"
                )
                retry_after[source] = datetime.now(UTC) + delay
                logger.info(
                    "current lane parked source=%s until=%s",
                    source,
                    retry_after[source].isoformat(),
                )
            elif pause > 0:
                source_pause = (
                    max(pause, settings.danistay_backfill_pause_seconds)
                    if source == "danistay" else pause
                )
                sleep(source_pause)
        if not progressed:
            if should_stop():
                break
            if earliest_retry is None:
                if not keep_alive:
                    break
                sleep(max(1.0, float(settings.poll_seconds)))
                continue
            wait_seconds = min(5.0, max(0.0, (earliest_retry - datetime.now(UTC)).total_seconds()))
            if wait_seconds > 0:
                sleep(wait_seconds)

    summary = {
        "status": "incremental" if then_incremental and not should_stop() else "stopped",
        "sources": sources,
        "completed": completed,
        "blocked": blocked,
        "remaining": remaining,
        "run_count": len(runs),
        "runs": runs,
    }
    if then_incremental and not should_stop():
        logger.info("full backfill finished; switching to incremental daemon")
        daemon(connection, should_stop=should_stop)
        summary["status"] = "incremental"
    return summary
