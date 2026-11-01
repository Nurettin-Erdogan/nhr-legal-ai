"""Backfill (arşiv) ve current (güncel) tarama şeritleri.

Aynı resmi portal aynı anda iki kez vurulmaz; kilit kanonik kaynak adındadır.
Checkpoint'ler ayrıdır: `yargitay` arşivi 2020'den yürür, `yargitay:current`
yalnız son ayları yeniden tarar.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from worker import ACTIVE_SOURCES
from worker.windows import month_window, next_month_start

Lane = Literal["backfill", "current"]

CURRENT_LANE_SOURCES = frozenset({"yargitay", "danistay", "kdk"})


def checkpoint_name(source: str, lane: Lane) -> str:
    source = source.strip().lower()
    if lane == "current":
        return f"{source}:current"
    return source


def canonical_source(job_name: str) -> str:
    name = job_name.strip().lower()
    if name.endswith(":current"):
        return name[: -len(":current")]
    return name


def daemon_jobs() -> tuple[tuple[str, Lane], ...]:
    jobs: list[tuple[str, Lane]] = []
    for source in ACTIVE_SOURCES:
        if source in CURRENT_LANE_SOURCES:
            jobs.append((source, "current"))
        jobs.append((source, "backfill"))
    return tuple(jobs)


def horizon_month(today: date, lookback_days: int) -> date:
    start = today - timedelta(days=max(1, lookback_days))
    return date(start.year, start.month, 1)


def resolve_sync_window(
    request: Any,
    cursor: dict[str, Any],
    *,
    corpus_start: date,
    today: date | None = None,
    lookback_days: int = 45,
) -> tuple[date, date]:
    """Takvim ayı pencereleri. Current şerit yalnızca son N güne yakın ayları döner."""
    if request.date_from and request.date_to:
        return request.date_from, request.date_to
    today = today or datetime.now(UTC).date()
    lane = getattr(request, "lane", "backfill")
    if lane == "current":
        return _current_window(cursor, today=today, lookback_days=lookback_days)
    if cursor.get("window_from") and cursor.get("window_to") and not cursor.get("window_complete"):
        return date.fromisoformat(cursor["window_from"]), date.fromisoformat(cursor["window_to"])
    start = request.date_from or (
        date.fromisoformat(cursor["next_window_start"])
        if cursor.get("next_window_start")
        else corpus_start
    )
    return month_window(start)


def _current_window(
    cursor: dict[str, Any],
    *,
    today: date,
    lookback_days: int,
) -> tuple[date, date]:
    horizon = horizon_month(today, lookback_days)
    if cursor.get("window_from") and cursor.get("window_to") and not cursor.get("window_complete"):
        window_from = date.fromisoformat(cursor["window_from"])
        if window_from >= horizon:
            return date.fromisoformat(cursor["window_from"]), date.fromisoformat(cursor["window_to"])
    start = (
        date.fromisoformat(cursor["next_window_start"])
        if cursor.get("next_window_start")
        else horizon
    )
    if start < horizon or start > today:
        start = horizon
    return month_window(start)


def wrap_current_next_start(window_from: date, *, today: date, lookback_days: int) -> date:
    nxt = next_month_start(window_from)
    if nxt > today:
        return horizon_month(today, lookback_days)
    return nxt


def advance_window_start(
    window_from: date,
    window_complete: bool,
    request: Any,
    *,
    today: date | None = None,
    lookback_days: int = 45,
) -> date:
    if not window_complete:
        return window_from
    today = today or datetime.now(UTC).date()
    if getattr(request, "lane", "backfill") == "current":
        return wrap_current_next_start(
            window_from, today=today, lookback_days=lookback_days
        )
    return next_month_start(window_from)
