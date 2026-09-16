"""Tek komutluk tarihsel backfill: checkpoint/resume, sonra incremental daemon."""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime
from time import sleep
from typing import Any, Callable

import psycopg

from worker import ACTIVE_SOURCES
from worker.config import get_worker_settings
from worker.jobs import run_sync
from worker.models import SyncRequest
from worker.repository import SyncRepository
from worker.scheduler import run_daemon

logger = logging.getLogger("worker.backfill")

DATE_WINDOW_SOURCES = frozenset({"yargitay", "danistay", "kdk"})


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
    return min(per_source, settings.full_corpus_start)


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
            return date.fromisoformat(next_start) > today
        return False
    return bool(cursor.get("complete"))


def apply_full_horizon(
    source: str,
    cursor: dict[str, Any] | None,
    *,
    horizon: date,
) -> dict[str, Any]:
    """Tarihsel ufku yeni bir başlangıca çek; mevcut imleç ufuğun ötesindeyse başa sar."""
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
    if cursor.get("full_horizon_start") == mark:
        return cursor
    return {
        "full_horizon_start": mark,
        "next_window_start": mark,
        "window_complete": True,
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

    completed: list[str] = []
    blocked: list[str] = []
    runs: list[dict[str, Any]] = []
    remaining = [source for source in sources if source not in completed]

    while remaining and not should_stop():
        progressed = False
        for source in list(remaining):
            if should_stop():
                break
            logger.info("full backfill starting source=%s", source)
            result = sync(
                connection,
                SyncRequest(source=source, lane="backfill", resume=True),
                should_stop=should_stop,
            )
            runs.append(result)
            progressed = True
            status = result.get("status")
            cursor = (result.get("checkpoint") or {}).get("last_cursor") or {}
            if embed and status not in {"failed", "captcha_required"}:
                result["embedding"] = embed_fn(connection)
            if status == "captcha_required":
                blocked.append(source)
                remaining.remove(source)
                logger.warning("full backfill blocked source=%s captcha", source)
                continue
            if is_historical_complete(source, cursor):
                completed.append(source)
                remaining.remove(source)
                logger.info("full backfill complete source=%s", source)
                continue
            if status in {"failed", "cancelled"}:
                sleep(max(pause, 5.0))
            elif pause > 0:
                sleep(pause)
        if not progressed:
            break

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
