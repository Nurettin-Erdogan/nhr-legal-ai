from __future__ import annotations

from calendar import monthrange
from datetime import date


def month_window(value: date) -> tuple[date, date]:
    last_day = monthrange(value.year, value.month)[1]
    return date(value.year, value.month, 1), date(value.year, value.month, last_day)


def next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def iter_month_windows(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz")
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        window_start, window_end = month_window(cursor)
        clipped_start = max(window_start, start)
        clipped_end = min(window_end, end)
        windows.append((clipped_start, clipped_end))
        cursor = next_month_start(cursor)
    return windows
