"""Resmi portallara karşı ortak HTTP retry politikası.

401/403 sürekli denenmez. 429 Retry-After ve 5xx üstel backoff + jitter kullanır.
Tek istek içindeki bekleme 8 saniyeyle sınırlıdır; daha uzun soğuma iş katmanındadır.
CAPTCHA bu katmanda çözülmez; çağıran işi durdurur.
"""

from __future__ import annotations

import random
from typing import Protocol


class RandomLike(Protocol):
    def random(self) -> float: ...


def is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def is_auth_blocked_status(status_code: int) -> bool:
    return status_code in {401, 403}


MAX_RETRY_WAIT_SECONDS = 8.0


def retry_wait_seconds(
    attempt: int,
    *,
    base_seconds: float,
    retry_after: str | None = None,
    jitter: bool = True,
    rng: RandomLike | None = None,
    max_seconds: float = MAX_RETRY_WAIT_SECONDS,
) -> float:
    wait = max(0.0, base_seconds) * (2 ** max(0, attempt - 1))
    if retry_after:
        try:
            wait = max(wait, float(retry_after))
        except ValueError:
            pass
    if jitter:
        generator = rng or random
        wait *= 0.8 + 0.4 * generator.random()
    if max_seconds >= 0:
        wait = min(wait, max_seconds)
    return wait
