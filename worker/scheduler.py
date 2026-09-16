from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import sleep
from typing import Callable

import psycopg

from worker.config import get_worker_settings
from worker.jobs import run_sync
from worker.lanes import Lane, checkpoint_name, daemon_jobs
from worker.models import SyncRequest
from worker.repository import SyncRepository

logger = logging.getLogger("worker.scheduler")


def due_jobs(
    connection: psycopg.Connection, now: datetime | None = None
) -> list[tuple[str, Lane]]:
    now = now or datetime.now(UTC)
    repo = SyncRepository(connection)
    due: list[tuple[str, Lane]] = []
    for source, lane in daemon_jobs():
        checkpoint = repo.get_checkpoint(checkpoint_name(source, lane))
        if checkpoint.next_run_at is None or checkpoint.next_run_at <= now:
            due.append((source, lane))
    return due


def due_sources(connection: psycopg.Connection, now: datetime | None = None) -> list[str]:
    """Geriye dönük: due olan backfill kaynak adları."""
    return [source for source, lane in due_jobs(connection, now) if lane == "backfill"]


def run_daemon(
    connection: psycopg.Connection,
    *,
    should_stop: Callable[[], bool],
    poll_seconds: int | None = None,
) -> None:
    settings = get_worker_settings()
    interval = poll_seconds or settings.poll_seconds
    logger.info(
        "ingestion daemon started poll=%ss current_lookback=%sd "
        "yargitay=%smin danistay=%smin mevzuat=%smin kdk=%smin aym=%smin",
        interval,
        settings.current_lookback_days,
        settings.yargitay_interval_minutes,
        settings.danistay_interval_minutes,
        settings.mevzuat_interval_minutes,
        settings.kdk_interval_minutes,
        settings.aym_interval_minutes,
    )
    while not should_stop():
        try:
            for source, lane in due_jobs(connection):
                if should_stop():
                    break
                logger.info("scheduled sync starting source=%s lane=%s", source, lane)
                result = run_sync(
                    connection, SyncRequest(source=source, lane=lane, resume=True)
                )
                logger.info(
                    "scheduled sync finished source=%s lane=%s status=%s run_id=%s",
                    source,
                    lane,
                    result.get("status"),
                    result.get("run_id"),
                )
        except Exception:
            logger.exception("daemon tick failed")
        remaining = interval
        while remaining > 0 and not should_stop():
            sleep(min(1, remaining))
            remaining -= 1
