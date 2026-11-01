"""Resmî kurum karar/kayıtlarını (KDK dışındaki yeni kaynaklar) sürümlü saklar.

KDK deposunun (`ingestion/kdk/store.py`) genellemesidir: kaynak adı, kurum ve yöntem
parametre olarak verilir; ilk kayıt, değişiklik (yeni sürüm) ve aynı içerik davranışı aynıdır.
Yalnız `source_type='other'` kayıtları yazar; resmî portaldan geldiği için `ready`dir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

from ingestion.chunk_store import replace_chunks
from ingestion.yargitay.chunking import DEFAULT_MAX_CHARS, chunk_text

IngestStatus = Literal["created", "updated", "unchanged", "new_version"]


@dataclass(frozen=True, slots=True)
class OfficialDoc:
    external_id: str
    title: str
    raw_text: str
    content_hash: str
    source_url: str
    decision_date: date | None
    fetched_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceProfile:
    authority: str
    canonical_source_name: str
    ingestion_method: str
    chunk_source: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    external_id: str
    status: IngestStatus
    legal_source_id: str
    chunk_count: int


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
    %(authority)s, 'TR', %(raw_text)s, %(metadata)s,
    %(decision_date)s, %(content_hash)s, 'ready', NOW(),
    %(canonical_source_name)s, %(source_url)s,
    %(ingestion_method)s, COALESCE(%(fetched_at)s, NOW()),
    COALESCE(%(fetched_at)s, NOW()), %(source_version)s, %(revision)s, TRUE
) RETURNING id
"""

_TOUCH_SOURCE = """
UPDATE legal_sources
SET title = %(title)s, source_url = %(source_url)s, official_source_url = %(source_url)s,
    metadata = metadata || %(metadata)s, last_ingested_at = NOW(),
    fetched_at = COALESCE(%(fetched_at)s, NOW()),
    last_verified_at = COALESCE(%(fetched_at)s, NOW()), ingest_status = 'ready'
WHERE id = %(id)s
"""

_UPDATE_CHANGED = """
UPDATE legal_sources
SET title = %(title)s, source_url = %(source_url)s, official_source_url = %(source_url)s,
    raw_text = %(raw_text)s, metadata = metadata || %(metadata)s, published_at = %(decision_date)s,
    content_hash = %(content_hash)s, last_ingested_at = NOW(),
    fetched_at = COALESCE(%(fetched_at)s, NOW()),
    last_verified_at = COALESCE(%(fetched_at)s, NOW()),
    source_version = %(source_version)s, revision = %(revision)s, ingest_status = 'ready'
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


def existing_external_ids(connection: psycopg.Connection, external_ids: list[str]) -> set[str]:
    if not external_ids:
        return set()
    rows = connection.execute(
        "SELECT external_id FROM legal_sources WHERE source_type = 'other' AND is_current AND external_id = ANY(%s)",
        (external_ids,),
    ).fetchall()
    return {row["external_id"] if isinstance(row, dict) else row[0] for row in rows}


def _write_chunks(cursor: psycopg.Cursor, legal_source_id: str, doc: OfficialDoc, profile: SourceProfile, max_chars: int) -> int:
    rows = [
        (
            legal_source_id,
            chunk.index,
            chunk.content,
            chunk.paragraph_start,
            chunk.paragraph_end,
            chunk.content_hash,
            Jsonb({"source": profile.chunk_source, "external_id": doc.external_id}),
        )
        for chunk in chunk_text(doc.raw_text, max_chars=max_chars)
    ]
    return replace_chunks(cursor, legal_source_id, rows)


def upsert_official_doc(
    connection: psycopg.Connection,
    doc: OfficialDoc,
    profile: SourceProfile,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestResult:
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(_SELECT_EXISTING, (doc.external_id,))
        existing = cursor.fetchone()
        values = {
            "title": doc.title,
            "source_url": doc.source_url,
            "external_id": doc.external_id,
            "raw_text": doc.raw_text,
            "metadata": Jsonb(doc.metadata),
            "decision_date": doc.decision_date,
            "content_hash": doc.content_hash,
            "fetched_at": doc.fetched_at,
            "source_version": f"sha256:{doc.content_hash[:16]}",
            "revision": 1 if existing is None else existing[3] + 1,
            "authority": profile.authority,
            "canonical_source_name": profile.canonical_source_name,
            "ingestion_method": profile.ingestion_method,
        }
        changed = existing is None or existing[1] != doc.content_hash
        if existing is not None and not changed:
            legal_source_id = existing[0]
            cursor.execute(_TOUCH_SOURCE, {**values, "id": legal_source_id})
            status: IngestStatus = "unchanged"
        elif existing is not None and existing[2]:
            cursor.execute(_SNAPSHOT, (existing[0],))
            cursor.execute("UPDATE legal_sources SET is_current = FALSE WHERE id = %s", (existing[0],))
            cursor.execute(_INSERT_SOURCE, values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute("UPDATE legal_sources SET superseded_by_id = %s WHERE id = %s", (legal_source_id, existing[0]))
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
            chunk_count = _write_chunks(cursor, legal_source_id, doc, profile, max_chunk_chars)
    return IngestResult(doc.external_id, status, str(legal_source_id), chunk_count)
