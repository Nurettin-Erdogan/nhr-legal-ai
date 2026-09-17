"""Portalın bildirdiği sonuç sayısı ile kayıt akıbetinin eşleşmesi."""

from __future__ import annotations

from typing import Any


def coverage_reconciled(
    *,
    expected: int | None,
    seen: int,
    stored: int,
    duplicate: int,
    quarantined: int,
    failed: int,
) -> bool:
    if expected is None or expected < 0:
        return False
    if seen != expected:
        return False
    if stored + duplicate + quarantined + failed != seen:
        return False
    if failed:
        return False
    return True


def window_may_advance(
    *,
    reconciled: bool,
    processed: int,
    failed: int,
    already_started: bool,
    stopped: bool = False,
) -> bool:
    """Move to the next month when this resume point has no portal rows left.

    Coverage mismatch must not pin backfill to a finished page for hours.
    A fresh window that returns nothing on the first request is left in place
    so a transient empty search cannot skip a month.
    """
    if stopped:
        return False
    if reconciled:
        return True
    return processed == 0 and failed == 0 and already_started


def coverage_cursor(
    *,
    expected: int | None,
    seen: int,
    stored: int,
    duplicate: int,
    quarantined: int,
    failed: int,
) -> dict[str, Any]:
    reconciled = coverage_reconciled(
        expected=expected,
        seen=seen,
        stored=stored,
        duplicate=duplicate,
        quarantined=quarantined,
        failed=failed,
    )
    return {
        "expected_count": expected,
        "seen_count": seen,
        "stored_count": stored,
        "duplicate_count": duplicate,
        "quarantined_count": quarantined,
        "failed_count": failed,
        "reconciled": reconciled,
        "window_complete": reconciled,
    }
