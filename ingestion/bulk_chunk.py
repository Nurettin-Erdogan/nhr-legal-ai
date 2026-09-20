"""Yerelde bekleyen bulk_seed kararlarını parçalar. HTTP yok."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from ingestion.yargitay.chunking import chunk_text

_COPY_SQL = """
COPY legal_chunks (
    legal_source_id, chunk_index, content,
    paragraph_start, paragraph_end, content_hash, metadata
) FROM STDIN
"""

CHECKPOINT = "bulk:pending_chunks"
ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")

_FETCH_SQL = """
SELECT ls.id, ls.raw_text, ls.external_id
FROM legal_sources ls
WHERE ls.ingestion_method = 'bulk_seed'
  AND ls.ingest_status = 'pending'
  AND ls.source_type = 'court_decision'
  AND ls.deleted_at IS NULL
  AND ls.is_current
  AND ls.id > %s
  AND mod(abs(hashtext(ls.id::text)), %s) = %s
  AND NOT EXISTS (
    SELECT 1 FROM legal_chunks chunk WHERE chunk.legal_source_id = ls.id
  )
ORDER BY ls.id
LIMIT %s
"""

def chunk_rows_for_source(
    legal_source_id: str,
    raw_text: str,
    external_id: str | None,
) -> list[tuple[Any, ...]]:
    chunks = chunk_text(raw_text or "")
    return [
        (
            legal_source_id,
            chunk.index,
            chunk.content,
            chunk.paragraph_start,
            chunk.paragraph_end,
            chunk.content_hash,
            Jsonb({"source": "bulk_seed", "external_id": external_id or ""}),
        )
        for chunk in chunks
    ]


def process_pending_seed_batch(
    connection,
    *,
    after_id: UUID,
    batch_size: int,
    shard: int = 0,
    shards: int = 1,
) -> dict[str, Any]:
    rows = connection.execute(
        _FETCH_SQL, (after_id, max(1, shards), shard % max(1, shards), batch_size)
    ).fetchall()
    if not rows:
        return {
            "last_id": str(after_id),
            "seen": 0,
            "chunked": 0,
            "skipped_empty": 0,
            "skipped_existing": 0,
            "chunks_written": 0,
            "done": True,
        }

    last_id = rows[-1]["id"] if isinstance(rows[0], dict) else rows[-1][0]

    chunked = 0
    skipped_empty = 0
    skipped_existing = 0
    outgoing: list[tuple[Any, ...]] = []
    for row in rows:
        source_id = row["id"] if isinstance(row, dict) else row[0]
        raw_text = row["raw_text"] if isinstance(row, dict) else row[1]
        external_id = row["external_id"] if isinstance(row, dict) else row[2]
        payload = chunk_rows_for_source(str(source_id), raw_text or "", external_id)
        if not payload:
            skipped_empty += 1
            continue
        outgoing.extend(payload)
        chunked += 1
    if outgoing:
        with connection.cursor() as cursor:
            with cursor.copy(_COPY_SQL) as copy:
                for item in outgoing:
                    metadata = item[-1]
                    payload = metadata.obj if hasattr(metadata, "obj") else metadata
                    copy.write_row(item[:-1] + (json.dumps(payload, ensure_ascii=False),))

    return {
        "last_id": str(last_id),
        "seen": len(rows),
        "chunked": chunked,
        "skipped_empty": skipped_empty,
        "skipped_existing": skipped_existing,
        "chunks_written": len(outgoing),
        "done": False,
    }
