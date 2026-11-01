"""Mevzuat maddelerinin `legal_sources` ve `legislation_details` tablolarına aktarımı.

Korpus aktarımı yönetimsel bir iştir ve `DATABASE_ADMIN_URL` ile çalışır.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from ingestion.chunk_store import replace_chunks
from ingestion.mevzuat.models import LegislationRecord
from ingestion.mevzuat.identity import validate_record_identity
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
    ls.revision,
    details.version_identity,
    details.version_date
FROM legal_sources ls
LEFT JOIN legislation_details details ON details.legal_source_id = ls.id
WHERE ls.source_type = 'legislation'
  AND ls.external_id = %s
  AND ls.is_current
FOR UPDATE OF ls
"""

_SELECT_VERSION = """
SELECT ls.id, ls.is_current
FROM legislation_details details
JOIN legal_sources ls ON ls.id = details.legal_source_id
WHERE details.legislation_identity_id = %s
  AND details.version_identity = %s
FOR UPDATE OF ls
"""

_SELECT_BY_CONTENT_HASH = """
SELECT ls.id, ls.is_current
FROM legislation_details details
JOIN legal_sources ls ON ls.id = details.legal_source_id
WHERE details.legislation_identity_id = %s
  AND ls.content_hash = %s
ORDER BY ls.is_current DESC, ls.revision DESC
LIMIT 1
"""

_SELECT_CURRENT_BY_IDENTITY = """
SELECT
    ls.id,
    ls.content_hash,
    EXISTS (
        SELECT 1
        FROM legal_chunks lc
        JOIN citations c ON c.legal_chunk_id = lc.id
        WHERE lc.legal_source_id = ls.id
    ) AS has_citations,
    ls.revision,
    details.version_identity,
    details.version_date
FROM legislation_details details
JOIN legal_sources ls ON ls.id = details.legal_source_id
WHERE details.legislation_identity_id = %s
  AND ls.is_current
FOR UPDATE OF ls
"""

_NEXT_REVISION = """
SELECT COALESCE(MAX(revision), 0) + 1
FROM legal_sources
WHERE source_type = 'legislation' AND external_id = %s
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
    is_current,
    superseded_by_id
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
    %(ingest_status)s,
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
    %(is_current)s,
    %(superseded_by_id)s
)
RETURNING id
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
    version_date = COALESCE(legislation_details.version_date, EXCLUDED.version_date),
    amendment_source = COALESCE(EXCLUDED.amendment_source, legislation_details.amendment_source)
"""

_COUNT_CHUNKS = "SELECT count(*) FROM legal_chunks WHERE legal_source_id = %s"


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


def version_identity_for(record: LegislationRecord) -> str:
    """Portal tarihi + metin hash'i. Aynı çift ikinci kez yazılmaz."""
    return f"{record.version_date or 'undated'}:{record.content_hash}"


def _unchanged_result(
    cursor: psycopg.Cursor,
    record: LegislationRecord,
    legal_source_id: object,
    *,
    max_chunk_chars: int,
) -> IngestResult:
    cursor.execute(_COUNT_CHUNKS, (legal_source_id,))
    chunk_count = cursor.fetchone()[0]
    if chunk_count == 0:
        chunk_count = _write_chunks(cursor, str(legal_source_id), record, max_chunk_chars)
    return IngestResult(
        external_id=record.external_id,
        status="unchanged",
        legal_source_id=str(legal_source_id),
        chunk_count=chunk_count,
    )


def _write_chunks(
    cursor: psycopg.Cursor,
    legal_source_id: str,
    record: LegislationRecord,
    max_chars: int,
) -> int:
    chunks = chunk_text(record.raw_text, max_chars=max_chars)
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
                    "source": "mevzuat",
                    "external_id": record.external_id,
                    "law_no": record.law_no,
                    "article_no": record.article_no,
                }
            ),
        )
        for chunk in chunks
    ]
    return replace_chunks(cursor, legal_source_id, rows)


def upsert_legislation(
    connection: psycopg.Connection,
    record: LegislationRecord,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestResult:
    """Maddeyi ve parçalarını tek transaction içinde yazar.

    Aynı ``version_identity`` veya aynı içerik hash'i tekrar gelirse satır
    overwrite edilmez; sonuç ``unchanged`` olur. Hash değişmişse eski current
    korunur ve yeni revision zincire eklenir.
    """
    validate_record_identity(record)
    version_identity = version_identity_for(record)
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(
            _UPSERT_IDENTITY,
            (record.legislation_type, record.law_no, record.article_no, record.law_name),
        )
        legislation_identity_id = cursor.fetchone()[0]
        cursor.execute(_SELECT_VERSION, (legislation_identity_id, version_identity))
        known_version = cursor.fetchone()
        if known_version is not None:
            return _unchanged_result(
                cursor, record, known_version[0], max_chunk_chars=max_chunk_chars
            )
        cursor.execute(
            _SELECT_BY_CONTENT_HASH, (legislation_identity_id, record.content_hash)
        )
        hashed = cursor.fetchone()
        if hashed is not None:
            return _unchanged_result(
                cursor, record, hashed[0], max_chunk_chars=max_chunk_chars
            )
        cursor.execute(_SELECT_CURRENT_BY_IDENTITY, (legislation_identity_id,))
        existing = cursor.fetchone()
        if existing is None:
            cursor.execute(_SELECT_EXISTING, (record.external_id,))
            existing = cursor.fetchone()
        cursor.execute(_NEXT_REVISION, (record.external_id,))
        next_revision = cursor.fetchone()[0]
        older_than_current = bool(
            existing is not None
            and record.version_date is not None
            and existing[5] is not None
            and record.version_date < existing[5]
        )
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
            "ingest_status": (
                "ready"
                if record.metadata.get("verified_against_gazette") is True
                and record.metadata.get("verified_against_mbs") is True
                else "pending"
            ),
            "source_version": version_identity,
            "revision": next_revision,
            "is_current": not older_than_current,
            "superseded_by_id": existing[0] if older_than_current else None,
        }
        details_values = {
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
        }
        try:
            with connection.transaction():
                if older_than_current:
                    cursor.execute(_INSERT_SOURCE, source_values)
                    legal_source_id = cursor.fetchone()[0]
                    cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
                    status: IngestStatus = "new_version"
                elif existing is not None:
                    cursor.execute(_SNAPSHOT_SOURCE, (existing[0],))
                    cursor.execute(
                        """
                        UPDATE legal_sources
                        SET is_current = FALSE,
                            effective_to = COALESCE(effective_to, CAST(%s AS date) - 1)
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
                    {"legal_source_id": legal_source_id, **details_values},
                )
                chunk_count = _write_chunks(
                    cursor, legal_source_id, record, max_chunk_chars
                )
        except UniqueViolation:
            cursor.execute(_SELECT_VERSION, (legislation_identity_id, version_identity))
            known_version = cursor.fetchone()
            if known_version is None:
                cursor.execute(
                    _SELECT_BY_CONTENT_HASH,
                    (legislation_identity_id, record.content_hash),
                )
                known_version = cursor.fetchone()
            if known_version is None:
                raise
            return _unchanged_result(
                cursor, record, known_version[0], max_chunk_chars=max_chunk_chars
            )

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
