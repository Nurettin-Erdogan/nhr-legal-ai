from __future__ import annotations

from ingestion.http import (
    is_auth_blocked_status,
    is_retryable_status,
    retry_wait_seconds,
)


class _FixedRng:
    def random(self) -> float:
        return 0.5


def test_retryable_and_auth_status_codes():
    assert is_retryable_status(429)
    assert is_retryable_status(503)
    assert not is_retryable_status(401)
    assert not is_retryable_status(403)
    assert not is_retryable_status(400)
    assert is_auth_blocked_status(401)
    assert is_auth_blocked_status(403)


def test_backoff_is_exponential_with_retry_after_and_jitter():
    assert retry_wait_seconds(1, base_seconds=2, jitter=False) == 2
    assert retry_wait_seconds(3, base_seconds=2, jitter=False) == 8
    assert retry_wait_seconds(1, base_seconds=2, retry_after="10", jitter=False) == 8
    wait = retry_wait_seconds(1, base_seconds=10, rng=_FixedRng())
    assert wait == 8
    assert retry_wait_seconds(1, base_seconds=2, retry_after="86400", jitter=False) == 8
