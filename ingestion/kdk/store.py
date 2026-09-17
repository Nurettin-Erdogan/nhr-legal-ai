"""KDK kararlarını genel resmî kaynak olarak güvenli ve sürümlü saklar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from ingestion.chunk_store import replace_chunks
from ingestion.kdk.models import KdkDecision
from ingestion.yargitay.chunking import DEFAULT_MAX_CHARS, chunk_text

IngestStatus = Literal["created", "updated", "unchanged", "new_version"]

_SELECT_EXISTING = """
SELECT ls.id, ls.content_hash,
       EXISTS (
           SELECT 1 FROM legal_chunks lc
           JOIN citations c ON c.legal_chunk_id = lc.id
           WHERE lc.legal_source_id = ls.id
       ) AS has_citations,
       ls.revision
FROM legal_sources ls
WHERE ls.source_type = 'other' AND ls.external_id = %s AND ls.is_current
FOR UPDATE OF ls
"""

_INSERT_SOURCE = """
INSERT INTO legal_sources (
    source_type, title, source_url, external_id, authority, jurisdiction,
    raw_text, metadata, published_at, content_hash, ingest_status,
    last_ingested_at, canonical_source_name, official_source_url,
    ingestion_method, fetched_at, last_verified_at, source_version,
    revision, is_current
) VALUES (
    'other', %(title)s, %(source_url)s, %(external_id)s,
    'Kamu Denetçiliği Kurumu', 'TR', %(raw_text)s, %(metadata)s,
    %(decision_date)s, %(content_hash)s, 'ready', NOW(),
    'KDK Kararlar Bilgi Bankası', %(source_url)s,
    'kdk_public_datatables_pdf', COALESCE(%(fetched_at)s, NOW()),
    COALESCE(%(fetched_at)s, NOW()), %(source_version)s, %(revision)s, TRUE
) RETURNING id
"""

_TOUCH_SOURCE = """
UPDATE legal_sources
SET title = %(title)s,
    source_url = %(source_url)s,
    official_source_url = %(source_url)s,
    metadata = metadata || %(metadata)s,
    last_ingested_at = NOW(),
    fetched_at = COALESCE(%(fetched_at)s, NOW()),
    last_verified_at = COALESCE(%(fetched_at)s, NOW()),
    ingest_status = 'ready'
WHERE id = %(id)s
"""

_UPDATE_CHANGED = """
UPDATE legal_sources
SET title = %(title)s,
    source_url = %(source_url)s,
    official_source_url = %(source_url)s,
    raw_text = %(raw_text)s,
    metadata = metadata || %(metadata)s,
    published_at = %(decision_date)s,
    content_hash = %(content_hash)s,
    last_ingested_at = NOW(),
    fetched_at = COALESCE(%(fetched_at)s, NOW()),
    last_verified_at = COALESCE(%(fetched_at)s, NOW()),
    source_version = %(source_version)s,
    revision = %(revision)s,
    ingest_status = 'ready'
WHERE id = %(id)s
"""

_SNAPSHOT = """
INSERT INTO legal_source_revisions (
    legal_source_id, revision, source_version, content_hash, raw_text,
    metadata, provenance, recorded_at
)
SELECT id, revision, source_version, content_hash, raw_text, metadata,
       jsonb_strip_nulls(jsonb_build_object(
           'authority', authority,
           'canonical_source_name', canonical_source_name,
           'official_source_url', official_source_url,
           'external_id', external_id,
           'ingestion_method', ingestion_method,
           'fetched_at', fetched_at,
           'last_verified_at', last_verified_at
       )), fetched_at
FROM legal_sources WHERE id = %s
ON CONFLICT (legal_source_id, revision) DO NOTHING
"""


@dataclass(frozen=True, slots=True)
class IngestResult:
    external_id: str
    status: IngestStatus
    legal_source_id: str
    chunk_count: int


def _write_chunks(
    cursor: psycopg.Cursor,
    legal_source_id: str,
    decision: KdkDecision,
    max_chars: int,
) -> int:
    chunks = chunk_text(decision.raw_text, max_chars=max_chars)
    rows = [
        (
            legal_source_id,
            chunk.index,
            chunk.content,
            chunk.paragraph_start,
            chunk.paragraph_end,
            chunk.content_hash,
            Jsonb(
                {
                    "source": "kdk",
                    "external_id": decision.external_id,
                    "decision_no": decision.decision_no,
                    "complaint_no": decision.complaint_no,
                }
            ),
        )
        for chunk in chunks
    ]
    return replace_chunks(cursor, legal_source_id, rows)


def upsert_decision(
    connection: psycopg.Connection,
    decision: KdkDecision,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestResult:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(_SELECT_EXISTING, (decision.external_id,))
        existing = cursor.fetchone()
        values = {
            "title": decision.title,
            "source_url": decision.source_url,
            "external_id": decision.external_id,
            "raw_text": decision.raw_text,
            "metadata": Jsonb(decision.metadata),
            "decision_date": decision.decision_date,
            "content_hash": decision.content_hash,
            "fetched_at": decision.fetched_at,
            "source_version": f"sha256:{decision.content_hash[:16]}",
            "revision": 1 if existing is None else existing[3] + 1,
        }
        changed = existing is None or existing[1] != decision.content_hash
        if existing is not None and not changed:
            legal_source_id = existing[0]
            cursor.execute(_TOUCH_SOURCE, {**values, "id": legal_source_id})
            status: IngestStatus = "unchanged"
        elif existing is not None and existing[2]:
            cursor.execute(_SNAPSHOT, (existing[0],))
            cursor.execute("UPDATE legal_sources SET is_current = FALSE WHERE id = %s", (existing[0],))
            cursor.execute(_INSERT_SOURCE, values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE legal_sources SET superseded_by_id = %s WHERE id = %s",
                (legal_source_id, existing[0]),
            )
            cursor.execute(_SNAPSHOT, (legal_source_id,))
            status = "new_version"
        elif existing is not None:
            cursor.execute(_SNAPSHOT, (existing[0],))
            legal_source_id = existing[0]
            cursor.execute(_UPDATE_CHANGED, {**values, "id": legal_source_id})
            cursor.execute(_SNAPSHOT, (legal_source_id,))
            status = "updated"
        else:
            cursor.execute(_INSERT_SOURCE, values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(_SNAPSHOT, (legal_source_id,))
            status = "created"

        cursor.execute("SELECT count(*) FROM legal_chunks WHERE legal_source_id = %s", (legal_source_id,))
        chunk_count = cursor.fetchone()[0]
        if status != "unchanged" or chunk_count == 0:
            chunk_count = _write_chunks(cursor, legal_source_id, decision, max_chunk_chars)

    return IngestResult(decision.external_id, status, str(legal_source_id), chunk_count)
