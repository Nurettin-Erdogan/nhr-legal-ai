from __future__ import annotations

import logging
from datetime import UTC, datetime
from time import sleep
from typing import Callable

import psycopg

from worker import ACTIVE_SOURCES
from worker.config import get_worker_settings
from worker.jobs import run_sync
from worker.models import SyncRequest
from worker.repository import SyncRepository

logger = logging.getLogger("worker.scheduler")


def due_sources(connection: psycopg.Connection, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    repo = SyncRepository(connection)
    due: list[str] = []
    for source in ACTIVE_SOURCES:
        checkpoint = repo.get_checkpoint(source)
        if checkpoint.next_run_at is None or checkpoint.next_run_at <= now:
            due.append(source)
    return due


def run_daemon(
    connection: psycopg.Connection,
    *,
    should_stop: Callable[[], bool],
    poll_seconds: int | None = None,
) -> None:
    settings = get_worker_settings()
    interval = poll_seconds or settings.poll_seconds
    logger.info(
        "ingestion daemon started poll=%ss yargitay=%smin danistay=%smin mevzuat=%smin kdk=%smin",
        interval,
        settings.yargitay_interval_minutes,
        settings.danistay_interval_minutes,
        settings.mevzuat_interval_minutes,
        settings.kdk_interval_minutes,
    )
    while not should_stop():
        try:
            for source in due_sources(connection):
                if should_stop():
                    break
                logger.info("scheduled sync starting source=%s", source)
                result = run_sync(connection, SyncRequest(source=source, resume=True))
                logger.info(
                    "scheduled sync finished source=%s status=%s run_id=%s",
                    source,
                    result.get("status"),
                    result.get("run_id"),
                )
        except Exception:
            logger.exception("daemon tick failed")
        remaining = interval
        while remaining > 0 and not should_stop():
            sleep(min(1, remaining))
            remaining -= 1
