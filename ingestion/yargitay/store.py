"""Kararların `legal_sources` ve `court_decision_details` tablolarına aktarımı.

Korpus aktarımı yönetimsel bir iştir ve `DATABASE_ADMIN_URL` ile çalışır;
`nhr_runtime` rolü hukuk kaynaklarına yazamaz.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from ingestion.yargitay.chunking import DEFAULT_MAX_CHARS, chunk_text
from ingestion.yargitay.models import CourtDecision

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
WHERE ls.source_type = 'court_decision'
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
    'court_decision',
    %(title)s,
    %(source_url)s,
    %(external_id)s,
    %(authority)s,
    'TR',
    %(raw_text)s,
    %(metadata)s,
    %(decision_date)s,
    %(content_hash)s,
    'ready',
    NOW(),
    %(canonical_source_name)s,
    %(source_url)s,
    %(ingestion_method)s,
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
    canonical_source_name = %(canonical_source_name)s,
    ingestion_method = %(ingestion_method)s,
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
    source_url = COALESCE(%(source_url)s, source_url),
    official_source_url = COALESCE(%(source_url)s, official_source_url),
    canonical_source_name = %(canonical_source_name)s,
    ingestion_method = %(ingestion_method)s,
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
INSERT INTO court_decision_details (
    legal_source_id,
    court_name,
    chamber,
    docket_no,
    decision_no,
    decision_date,
    decision_type,
    outcome
)
VALUES (
    %(legal_source_id)s,
    %(court_name)s,
    %(chamber)s,
    %(docket_no)s,
    %(decision_no)s,
    %(decision_date)s,
    %(decision_type)s,
    %(outcome)s
)
ON CONFLICT (legal_source_id) DO UPDATE SET
    court_name = EXCLUDED.court_name,
    chamber = EXCLUDED.chamber,
    docket_no = EXCLUDED.docket_no,
    decision_no = EXCLUDED.decision_no,
    decision_date = EXCLUDED.decision_date,
    decision_type = EXCLUDED.decision_type,
    outcome = EXCLUDED.outcome
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


class CitedDecisionChangedError(RuntimeError):
    """A cited decision changed and its stable chunks cannot be replaced."""


def _write_chunks(
    cursor: psycopg.Cursor,
    legal_source_id: str,
    decision: CourtDecision,
    max_chars: int,
) -> int:
    cursor.execute(_DELETE_CHUNKS, (legal_source_id,))

    chunks = chunk_text(decision.raw_text, max_chars=max_chars)
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
                        "source": decision.metadata.get("source_adapter", "yargitay"),
                        "external_id": decision.external_id,
                    }
                ),
            ),
        )

    return len(chunks)


def upsert_decision(
    connection: psycopg.Connection,
    decision: CourtDecision,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestResult:
    """Kararı ve parçalarını tek transaction içinde yazar.

    Metin değişmediyse parçalar yeniden üretilmez; böylece kaynağa verilmiş
    atıflar korunur.
    """
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(_SELECT_EXISTING, (decision.external_id,))
        existing = cursor.fetchone()

        content_changed = existing is None or existing[1] != decision.content_hash
        source_values = {
                "title": decision.title,
                "source_url": decision.source_url,
                "external_id": decision.external_id,
                "authority": decision.court_name,
                "raw_text": decision.raw_text,
                "metadata": Jsonb(decision.metadata),
                "decision_date": decision.decision_date,
                "content_hash": decision.content_hash,
                "fetched_at": decision.scraped_at,
                "source_version": f"sha256:{decision.content_hash[:16]}",
                "revision": 1 if existing is None else existing[3] + 1,
                "canonical_source_name": decision.metadata.get(
                    "canonical_source_name", "Yargıtay Karar Arama"
                ),
                "ingestion_method": decision.metadata.get(
                    "ingestion_method", "yargitay_public_json_http"
                ),
            }

        if existing is not None and not content_changed:
            legal_source_id = existing[0]
            cursor.execute(
                _TOUCH_SOURCE,
                {**source_values, "id": legal_source_id},
            )
            status: IngestStatus = "unchanged"
        elif existing is not None and existing[2]:
            cursor.execute(_SNAPSHOT_SOURCE, (existing[0],))
            cursor.execute(
                "UPDATE legal_sources SET is_current = FALSE WHERE id = %s",
                (existing[0],),
            )
            cursor.execute(_INSERT_SOURCE, source_values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(
                "UPDATE legal_sources SET superseded_by_id = %s WHERE id = %s",
                (legal_source_id, existing[0]),
            )
            cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
            status = "new_version"
        elif existing is not None:
            cursor.execute(_SNAPSHOT_SOURCE, (existing[0],))
            legal_source_id = existing[0]
            cursor.execute(
                _UPDATE_CHANGED,
                {**source_values, "id": legal_source_id},
            )
            cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
            status = "updated"
        else:
            cursor.execute(_INSERT_SOURCE, source_values)
            legal_source_id = cursor.fetchone()[0]
            cursor.execute(_SNAPSHOT_SOURCE, (legal_source_id,))
            status = "created"

        cursor.execute(
            _UPSERT_DETAILS,
            {
                "legal_source_id": legal_source_id,
                "court_name": decision.court_name,
                "chamber": decision.chamber,
                "docket_no": decision.docket_no,
                "decision_no": decision.decision_no,
                "decision_date": decision.decision_date,
                "decision_type": decision.metadata.get("decision_type"),
                "outcome": decision.metadata.get("outcome"),
            },
        )

        cursor.execute(_COUNT_CHUNKS, (legal_source_id,))
        chunk_count = cursor.fetchone()[0]

        if status != "unchanged" or chunk_count == 0:
            chunk_count = _write_chunks(cursor, legal_source_id, decision, max_chunk_chars)

    return IngestResult(
        external_id=decision.external_id,
        status=status,
        legal_source_id=str(legal_source_id),
        chunk_count=chunk_count,
    )


def ingest_decisions(
    connection: psycopg.Connection,
    decisions: Iterable[CourtDecision],
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHARS,
) -> IngestSummary:
    summary = IngestSummary()

    for decision in decisions:
        result = upsert_decision(connection, decision, max_chunk_chars=max_chunk_chars)
        summary = summary.with_result(result)
        logger.info(
            "%s | %s | %s parça",
            result.status,
            result.external_id,
            result.chunk_count,
        )

    return summary
