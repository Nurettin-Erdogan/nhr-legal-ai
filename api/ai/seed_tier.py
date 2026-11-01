"""Doğrulanmamış toplu katmanın o an taranabilir olup olmadığını izleyen sigorta.

Toplu katmanın sözcük dizini 31 GB'tır. Arkada yoğun veri işi (toplama, embedding) çalışırken bellekte kalamaz: ölçülen bir
aramada dizin taraması 5,6 sn, satır okuması 4,9 sn sürdü, oysa resmî katman aynı sorguda 0,26 sn'de bitti (2026-10-10). Böyle
bir dönemde her arama toplu katmanı bekleyip zaman aşımına düşüyor, kullanıcı her seferinde saniyelerce boşa bekliyordu.

Sigorta yalnız şunu yapar: toplu katman art arda `threshold` kez zaman aşımına uğrarsa `cooldown` saniye boyunca denenmez;
arama doğrudan resmî katmanla döner ve sonuç "kısmi" işaretlenir. Süre dolunca bir kez yeniden denenir: yetişirse sigorta
kapanır, yetişmezse yeniden açılır. Doğrulanmamış kayıtların resmî gibi sunulmasıyla ilgisi yoktur: o dönemde hiç taranmazlar.
Durum süreç belleğindedir (API yeniden başlayınca sıfırlanır) ve hukuk aramasıyla asistan araması arasında ortaktır.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TierBreaker:
    def __init__(self, *, threshold: int = 3, cooldown: float = 120.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._open_until: float | None = None

    def allow(self) -> bool:
        """Toplu katman şimdi denensin mi (kapalıyken ya da bekleme süresi dolduğunda evet)."""
        with self._lock:
            return self._open_until is None or self._clock() >= self._open_until

    def record(self, succeeded: bool) -> None:
        """Toplu katmanı tarayan bir denemenin sonucu: yetişti ya da zaman aşımına uğradı."""
        with self._lock:
            if succeeded:
                self._failures = 0
                self._open_until = None
                return
            self._failures += 1
            if self._failures >= self.threshold:
                self._open_until = self._clock() + self.cooldown

    def reset(self) -> None:
        with self._lock:
            self._failures = 0
            self._open_until = None

    @property
    def is_open(self) -> bool:
        return not self.allow()


seed_tier = TierBreaker()
