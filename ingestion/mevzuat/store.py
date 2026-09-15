"""Mevzuat maddelerinin `legal_sources` ve `legislation_details` tablolarına aktarımı.

Korpus aktarımı yönetimsel bir iştir ve `DATABASE_ADMIN_URL` ile çalışır.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from ingestion.mevzuat.models import LegislationRecord
from ingestion.yargitay.chunking import DEFAULT_MAX_CHARS, chunk_text

logger = logging.getLogger(__name__)

IngestStatus = Literal["created", "updated", "unchanged", "new_version"]

_SELECT_EXISTING = """
SELECT
    ls.id,
    ls.content_hash,
    EXISTS (
        SELECT 1
        FROM legal_chunks lc
        JOIN citations c ON c.legal_chunk_id = lc.id
        WHERE lc.legal_source_id = ls.id
    ) AS has_citations,
    ls.revision
FROM legal_sources ls
WHERE ls.source_type = 'legislation'
  AND ls.external_id = %s
  AND ls.is_current
FOR UPDATE OF ls
"""

_INSERT_SOURCE = """
INSERT INTO legal_sources (
    source_type,
    title,
    source_url,
    external_id,
    authority,
    jurisdiction,
    raw_text,
    metadata,
    published_at,
    content_hash,
    ingest_status,
    last_ingested_at,
    effective_from,
    effective_to,
    canonical_source_name,
    official_source_url,
    ingestion_method,
    fetched_at,
    last_verified_at,
    source_version,
    revision,
    is_current
)
VALUES (
    'legislation',
    %(title)s,
    %(source_url)s,
    %(external_id)s,
    %(authority)s,
    'TR',
    %(raw_text)s,
    %(metadata)s,
    %(published_at)s,
    %(content_hash)s,
    'ready',
    NOW(),
    %(effective_from)s,
    %(effective_to)s,
    'Mevzuat Bilgi Sistemi',
    %(source_url)s,
    'bedesten_public_json_http',
    COALESCE(%(fetched_at)s, NOW()),
    COALESCE(%(fetched_at)s, NOW()),
    %(source_version)s,
    %(revision)s,
    TRUE
)
RETURNING id
"""

_TOUCH_SOURCE = """
UPDATE legal_sources
SET title = %(title)s,
    source_url = COALESCE(%(source_url)s, source_url),
    official_source_url = COALESCE(%(source_url)s, official_source_url),
    metadata = metadata || %(metadata)s,
    published_at = COALESCE(%(published_at)s, published_at),
    last_ingested_at = NOW(),
    fetched_at = COALESCE(%(fetched_at)s, NOW()),
    last_verified_at = COALESCE(%(fetched_at)s, NOW()),
    ingest_status = 'ready'
WHERE id = %(id)s
"""

_UPSERT_IDENTITY = """
INSERT INTO legislation_identities (
    legislation_type, law_no, article_no, canonical_name
)
VALUES (%s, %s, %s, %s)
ON CONFLICT (legislation_type, law_no, article_no) DO UPDATE
SET canonical_name = EXCLUDED.canonical_name, updated_at = NOW()
RETURNING id
"""

_SNAPSHOT_SOURCE = """
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

_UPSERT_DETAILS = """
INSERT INTO legislation_details (
    legal_source_id,
    legislation_type,
    law_name,
    law_no,
    article_no,
    article_title,
    official_gazette_no,
    official_gazette_date,
    version_date,
    legislation_identity_id,
    version_identity,
    amendment_source
)
VALUES (
    %(legal_source_id)s,
    %(legislation_type)s,
    %(law_name)s,
    %(law_no)s,
    %(article_no)s,
    %(article_title)s,
    %(official_gazette_no)s,
    %(official_gazette_date)s,
    %(version_date)s,
    %(legislation_identity_id)s,
    %(version_identity)s,
    %(amendment_source)s
)
ON CONFLICT (legal_source_id) DO UPDATE SET
    legislation_type = EXCLUDED.legislation_type,
    law_name = EXCLUDED.law_name,
    law_no = EXCLUDED.law_no,
    article_no = EXCLUDED.article_no,
    article_title = EXCLUDED.article_title,
    official_gazette_no = EXCLUDED.official_gazette_no,
    official_gazette_date = EXCLUDED.official_gazette_date,
    version_date = EXCLUDED.version_date,
    legislation_identity_id = EXCLUDED.legislation_identity_id,
    version_identity = EXCLUDED.version_identity,
    amendment_source = EXCLUDED.amendment_source
"""

_COUNT_CHUNKS = "SELECT count(*) FROM legal_chunks WHERE legal_source_id = %s"
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


@dataclass(frozen=True, slots=True)
class IngestResult:
    external_id: str
    status: IngestStatus
    legal_source_id: str
    chunk_count: int


@dataclass(frozen=True, slots=True)
class IngestSummary:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    new_version: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged + self.new_version

    def with_result(self, result: IngestResult) -> IngestSummary:
        return IngestSummary(
            created=self.created + (result.status == "created"),
            updated=self.updated + (result.status == "updated"),
            unchanged=self.unchanged + (result.status == "unchanged"),
            new_version=self.new_version + (result.status == "new_version"),
        )


class CitedLegislationChangedError(RuntimeError):
    """Atıf verilmiş bir madde değişti; parçalar korunarak aktarım durdu."""


def _write_chunks(
    cursor: psycopg.Cursor,
    legal_source_id: str,
    record: LegislationRecord,
    max_chars: int,
) -> int:
    cursor.execute(_DELETE_CHUNKS, (legal_source_id,))
    chunks = chunk_text(record.raw_text, max_chars=max_chars)
    for chunk in chunks:
        cursor.execute(
            _INSERT_CHUNK,
            (
                legal_source_id,
                chunk.index,
                chunk.content,
                chunk.paragraph_start,
                chunk.paragraph_end,
                chunk.content_hash,
                Jsonb(
                    {
                        "source": "mevzuat",
                        "external_id": record.external_id,
                        "law_no": record.law_no,
                        "article_no": record.article_no,
                    }
                ),
            ),
        )
    return len(chunks)


def upsert_legislation(
    connection: psycopg.Connection,
    record: LegislationRecord,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestResult:
    """Maddeyi ve parçalarını tek transaction içinde yazar."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(_SELECT_EXISTING, (record.external_id,))
        existing = cursor.fetchone()
        content_changed = existing is None or existing[1] != record.content_hash
        version_identity = f"{record.version_date or 'undated'}:{record.content_hash}"
        source_values = {
                "title": record.title,
                "source_url": record.source_url,
                "external_id": record.external_id,
                "authority": "Mevzuat Bilgi Sistemi",
                "raw_text": record.raw_text,
                "metadata": Jsonb(record.metadata),
                "published_at": record.official_gazette_date,
                "content_hash": record.content_hash,
                "effective_from": record.effective_from,
                "effective_to": record.effective_to,
                "fetched_at": record.scraped_at,
                "source_version": version_identity,
                "revision": 1 if existing is None else existing[3] + 1,
            }
        cursor.execute(
            _UPSERT_IDENTITY,
            (record.legislation_type, record.law_no, record.article_no, record.law_name),
        )
        legislation_identity_id = cursor.fetchone()[0]

        if existing is not None and not content_changed:
            legal_source_id = existing[0]
            cursor.execute(_TOUCH_SOURCE, {**source_values, "id": legal_source_id})
            status: IngestStatus = "unchanged"
        elif existing is not None:
            cursor.execute(_SNAPSHOT_SOURCE, (existing[0],))
            cursor.execute(
                """
                UPDATE legal_sources
                SET is_current = FALSE,
                    effective_to = COALESCE(
                        effective_to,
                        CAST(%s AS date),
                        CURRENT_DATE
                    )
                WHERE id = %s
                """,
                (record.effective_from, existing[0]),
            )
            cursor.execute(_INSERT_SOURCE, source_values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE legal_sources SET superseded_by_id = %s WHERE id = %s",
                (legal_source_id, existing[0]),
            )
            cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
            status = "new_version"
        else:
            cursor.execute(_INSERT_SOURCE, source_values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
            status = "created"
        cursor.execute(
            _UPSERT_DETAILS,
            {
                "legal_source_id": legal_source_id,
                "legislation_type": record.legislation_type,
                "law_name": record.law_name,
                "law_no": record.law_no,
                "article_no": record.article_no,
                "article_title": record.article_title,
                "official_gazette_no": record.official_gazette_no,
                "official_gazette_date": record.official_gazette_date,
                "version_date": record.version_date,
                "legislation_identity_id": legislation_identity_id,
                "version_identity": version_identity,
                "amendment_source": record.amendment_source,
            },
        )
        cursor.execute(_COUNT_CHUNKS, (legal_source_id,))
        chunk_count = cursor.fetchone()[0]
        if status != "unchanged" or chunk_count == 0:
            chunk_count = _write_chunks(cursor, legal_source_id, record, max_chunk_chars)

    return IngestResult(
        external_id=record.external_id,
        status=status,
        legal_source_id=str(legal_source_id),
        chunk_count=chunk_count,
    )


def ingest_legislation(
    connection: psycopg.Connection,
    records: Iterable[LegislationRecord],
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestSummary:
    summary = IngestSummary()
    for record in records:
        result = upsert_legislation(connection, record, max_chunk_chars=max_chunk_chars)
        summary = summary.with_result(result)
        logger.info("%s | %s | %s parça", result.status, result.external_id, result.chunk_count)
    return summary
