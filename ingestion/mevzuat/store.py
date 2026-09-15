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

IngestStatus = Literal["created", "updated", "unchanged"]

_SELECT_EXISTING = """
SELECT
    ls.id,
    ls.content_hash,
    EXISTS (
        SELECT 1
        FROM legal_chunks lc
        JOIN citations c ON c.legal_chunk_id = lc.id
        WHERE lc.legal_source_id = ls.id
    ) AS has_citations
FROM legal_sources ls
WHERE ls.source_type = 'legislation'
  AND ls.external_id = %s
FOR UPDATE OF ls
"""

_UPSERT_SOURCE = """
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
    last_ingested_at
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
    NOW()
)
ON CONFLICT (source_type, external_id) WHERE external_id IS NOT NULL
DO UPDATE SET
    title = EXCLUDED.title,
    source_url = COALESCE(EXCLUDED.source_url, legal_sources.source_url),
    authority = EXCLUDED.authority,
    raw_text = EXCLUDED.raw_text,
    metadata = legal_sources.metadata || EXCLUDED.metadata,
    published_at = EXCLUDED.published_at,
    content_hash = EXCLUDED.content_hash,
    ingest_status = 'ready',
    last_ingested_at = NOW()
RETURNING id
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
    version_date
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
    %(version_date)s
)
ON CONFLICT (legal_source_id) DO UPDATE SET
    legislation_type = EXCLUDED.legislation_type,
    law_name = EXCLUDED.law_name,
    law_no = EXCLUDED.law_no,
    article_no = EXCLUDED.article_no,
    article_title = EXCLUDED.article_title,
    official_gazette_no = EXCLUDED.official_gazette_no,
    official_gazette_date = EXCLUDED.official_gazette_date,
    version_date = EXCLUDED.version_date
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

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged

    def with_result(self, result: IngestResult) -> IngestSummary:
        return IngestSummary(
            created=self.created + (result.status == "created"),
            updated=self.updated + (result.status == "updated"),
            unchanged=self.unchanged + (result.status == "unchanged"),
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
        if existing is not None and content_changed and existing[2]:
            raise CitedLegislationChangedError(
                "Atıf verilmiş mevzuat metni değişti; parçalar korunarak aktarım durduruldu: "
                f"{record.external_id}"
            )

        cursor.execute(
            _UPSERT_SOURCE,
            {
                "title": record.title,
                "source_url": record.source_url,
                "external_id": record.external_id,
                "authority": "Mevzuat Bilgi Sistemi",
                "raw_text": record.raw_text,
                "metadata": Jsonb(record.metadata),
                "published_at": record.official_gazette_date,
                "content_hash": record.content_hash,
            },
        )
        legal_source_id = cursor.fetchone()[0]
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
            },
        )
        cursor.execute(_COUNT_CHUNKS, (legal_source_id,))
        chunk_count = cursor.fetchone()[0]
        if content_changed or chunk_count == 0:
            chunk_count = _write_chunks(cursor, legal_source_id, record, max_chunk_chars)

        if existing is None:
            status: IngestStatus = "created"
        elif content_changed:
            status = "updated"
        else:
            status = "unchanged"

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
