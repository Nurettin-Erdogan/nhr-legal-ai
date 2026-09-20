"""Toplu parcalama bitti mi? 12 sharda da `complete` ise DONE yazar (NOT/ERR aksi halde)."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
SHARDS = 12

try:
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], connect_timeout=5) as connection:
        rows = connection.execute(
            "SELECT last_cursor FROM source_sync_checkpoints WHERE source_name LIKE %s",
            (f"bulk:pending_chunks:%/{SHARDS}",),
        ).fetchall()
    print("DONE" if len(rows) == SHARDS and all(row[0].get("complete") for row in rows) else "NOT")
except Exception:  # noqa: BLE001
    print("ERR")
