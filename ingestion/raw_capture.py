"""Resmî HTTP gövdelerini parse edilmeden önce diske yazar."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "__", value)[:180]


def save_raw_response(
    *,
    root: Path | str,
    source: str,
    record_id: str,
    url: str,
    method: str,
    body: bytes,
    request: Any | None = None,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(UTC)
    digest = hashlib.sha256(body).hexdigest()
    folder = Path(root) / source / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(f"{source}__{record_id}__{digest[:16]}")
    payload_path = folder / f"{stem}.bin"
    meta_path = folder / f"{stem}.json"
    payload_path.write_bytes(body)
    meta = {
        "source": source,
        "record_id": record_id,
        "url": url,
        "method": method,
        "request": request,
        "fetched_at": fetched_at.isoformat(),
        "sha256": digest,
        "byte_length": len(body),
        "payload_file": payload_path.name,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
