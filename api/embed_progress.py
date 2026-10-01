"""Embedding hazır sayısı: 21M satırda count(*) zaman aşımına uğrar, kutu donar.

Embed işçisi her turda bu dosyayı günceller; /stats canlı overlay olarak okur.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROGRESS_FILE = Path(__file__).resolve().parents[1] / "data" / "cache" / "embed_progress.json"
_SLOW_COUNTS_FILE = Path(__file__).resolve().parents[1] / "data" / "cache" / "slow_counts.json"


def read_ready() -> int | None:
    if "pytest" in sys.modules:
        return None
    try:
        raw = json.loads(PROGRESS_FILE.read_text(encoding="utf-8-sig"))
        ready = int(raw["ready"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return ready if ready >= 0 else None


def baseline_ready() -> int:
    values = [0]
    try:
        values.append(int(json.loads(_SLOW_COUNTS_FILE.read_text(encoding="utf-8-sig"))["chunk_embedded_count"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        values.append(int(json.loads(PROGRESS_FILE.read_text(encoding="utf-8-sig"))["ready"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return max(values)


def write_ready(ready: int) -> None:
    if "pytest" in sys.modules:
        return
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"ready": int(ready), "ts": time.time()})
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(PROGRESS_FILE)
