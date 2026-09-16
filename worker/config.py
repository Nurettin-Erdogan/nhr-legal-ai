from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from dotenv import load_dotenv


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return max(1, int(raw))


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return max(0.0, float(raw))


def _date_env(name: str, default: date) -> date:
    raw = os.getenv(name)
    if not raw:
        return default
    return date.fromisoformat(raw.strip())


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


DEFAULT_MEVZUAT_DISCOVERY_TYPES = (
    "KANUN",
    "KHK",
    "CB_KARARNAME",
    "TUZUK",
    "YONETMELIK",
    "CB_YONETMELIK",
    "TEBLIGLER",
    "CB_KARAR",
    "CB_GENELGE",
)


@dataclass(frozen=True, slots=True)
class WorkerSettings:
    database_url: str
    yargitay_interval_minutes: int
    danistay_interval_minutes: int
    mevzuat_interval_minutes: int
    kdk_interval_minutes: int
    aym_interval_minutes: int
    yargitay_backfill_interval_minutes: int
    danistay_backfill_interval_minutes: int
    mevzuat_backfill_interval_minutes: int
    kdk_backfill_interval_minutes: int
    aym_backfill_interval_minutes: int
    poll_seconds: int
    yargitay_delay_seconds: float
    danistay_delay_seconds: float
    mevzuat_delay_seconds: float
    kdk_delay_seconds: float
    aym_delay_seconds: float
    yargitay_max_records: int
    danistay_max_records: int
    mevzuat_max_articles: int
    kdk_max_records: int
    aym_max_records: int
    yargitay_corpus_start: date
    danistay_corpus_start: date
    kdk_corpus_start: date
    snapshot_dir: str
    max_retries: int
    current_lookback_days: int
    current_interval_minutes: int
    current_retry_interval_minutes: int
    full_corpus_start: date
    backfill_pause_seconds: float
    mevzuat_discovery_types: tuple[str, ...]
    embed_after_sync: bool
    embed_limit_per_run: int
    embed_batch_size: int
    embed_delay_seconds: float


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    load_dotenv()
    database_url = os.getenv("DATABASE_ADMIN_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Worker için DATABASE_ADMIN_URL tanımlı olmalıdır")
    return WorkerSettings(
        database_url=database_url,
        yargitay_interval_minutes=_int_env("YARGITAY_SYNC_INTERVAL_MINUTES", 360),
        danistay_interval_minutes=_int_env("DANISTAY_SYNC_INTERVAL_MINUTES", 720),
        mevzuat_interval_minutes=_int_env("MEVZUAT_SYNC_INTERVAL_MINUTES", 720),
        kdk_interval_minutes=_int_env("KDK_SYNC_INTERVAL_MINUTES", 1440),
        aym_interval_minutes=_int_env("AYM_SYNC_INTERVAL_MINUTES", 1440),
        yargitay_backfill_interval_minutes=_int_env("YARGITAY_BACKFILL_INTERVAL_MINUTES", 60),
        danistay_backfill_interval_minutes=_int_env("DANISTAY_BACKFILL_INTERVAL_MINUTES", 90),
        mevzuat_backfill_interval_minutes=_int_env("MEVZUAT_BACKFILL_INTERVAL_MINUTES", 120),
        kdk_backfill_interval_minutes=_int_env("KDK_BACKFILL_INTERVAL_MINUTES", 180),
        aym_backfill_interval_minutes=_int_env("AYM_BACKFILL_INTERVAL_MINUTES", 180),
        poll_seconds=_int_env("WORKER_POLL_SECONDS", 30),
        yargitay_delay_seconds=_float_env("YARGITAY_DELAY_SECONDS", 1.5),
        danistay_delay_seconds=_float_env("DANISTAY_DELAY_SECONDS", 2.0),
        mevzuat_delay_seconds=_float_env("MEVZUAT_DELAY_SECONDS", 1.0),
        kdk_delay_seconds=_float_env("KDK_DELAY_SECONDS", 2.0),
        aym_delay_seconds=_float_env("AYM_DELAY_SECONDS", 2.0),
        yargitay_max_records=_int_env("YARGITAY_MAX_RECORDS_PER_RUN", 40),
        danistay_max_records=_int_env("DANISTAY_MAX_RECORDS_PER_RUN", 30),
        mevzuat_max_articles=_int_env("MEVZUAT_MAX_ARTICLES_PER_RUN", 30),
        kdk_max_records=_int_env("KDK_MAX_RECORDS_PER_RUN", 20),
        aym_max_records=_int_env("AYM_MAX_RECORDS_PER_RUN", 20),
        yargitay_corpus_start=_date_env("YARGITAY_CORPUS_START", date(2020, 1, 1)),
        danistay_corpus_start=_date_env("DANISTAY_CORPUS_START", date(2020, 1, 1)),
        kdk_corpus_start=_date_env("KDK_CORPUS_START", date(2020, 1, 1)),
        snapshot_dir=os.getenv("INGESTION_SNAPSHOT_DIR", "data/raw").strip() or "data/raw",
        max_retries=_int_env("INGESTION_MAX_RETRIES", 3),
        current_lookback_days=_int_env("CURRENT_LOOKBACK_DAYS", 45),
        current_interval_minutes=_int_env("CURRENT_SYNC_INTERVAL_MINUTES", 180),
        current_retry_interval_minutes=_int_env("CURRENT_RETRY_INTERVAL_MINUTES", 60),
        full_corpus_start=_date_env("FULL_CORPUS_START", date(1980, 1, 1)),
        backfill_pause_seconds=_float_env("BACKFILL_PAUSE_SECONDS", 2.0),
        mevzuat_discovery_types=_csv_env(
            "MEVZUAT_DISCOVERY_TYPES", DEFAULT_MEVZUAT_DISCOVERY_TYPES
        ),
        embed_after_sync=_bool_env("EMBED_AFTER_SYNC", True),
        embed_limit_per_run=_int_env("EMBED_LIMIT_PER_RUN", 200),
        embed_batch_size=_int_env("EMBED_BATCH_SIZE", 10),
        embed_delay_seconds=_float_env("EMBED_DELAY_SECONDS", 0.0),
    )
