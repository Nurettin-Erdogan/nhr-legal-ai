"""legal_chunks satırlarını tek round-trip ile yaz."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_DELETE_CHUNKS = "DELETE FROM legal_chunks WHERE legal_source_id = %s"

_INSERT_CHUNK = """
INSERT INTO legal_chunks (
    legal_source_id,
    chunk_index,
    content,
    paragraph_start,
    paragraph_end,
    content_hash,
    metadata
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def replace_chunks(cursor: Any, legal_source_id: str, rows: Sequence[tuple[Any, ...]]) -> int:
    cursor.execute(_DELETE_CHUNKS, (legal_source_id,))
    if not rows:
        return 0
    cursor.executemany(_INSERT_CHUNK, rows)
    return len(rows)
