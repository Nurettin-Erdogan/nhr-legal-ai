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
WHERE ls.source_type = 'court_decision'
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
INSERT INTO court_decision_details (
    legal_source_id,
    court_name,
    chamber,
    docket_no,
    decision_no,
    decision_date,
    decision_type
)
VALUES (
    %(legal_source_id)s,
    %(court_name)s,
    %(chamber)s,
    %(docket_no)s,
    %(decision_no)s,
    %(decision_date)s,
    %(decision_type)s
)
ON CONFLICT (legal_source_id) DO UPDATE SET
    court_name = EXCLUDED.court_name,
    chamber = EXCLUDED.chamber,
    docket_no = EXCLUDED.docket_no,
    decision_no = EXCLUDED.decision_no,
    decision_date = EXCLUDED.decision_date,
    decision_type = EXCLUDED.decision_type
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
                Jsonb({"source": "yargitay", "external_id": decision.external_id}),
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
        if existing is not None and content_changed and existing[2]:
            raise CitedDecisionChangedError(
                f"Atif verilmis karar metni degisti; chunk'lar korunarak aktarim durduruldu: "
                f"{decision.external_id}"
            )

        cursor.execute(
            _UPSERT_SOURCE,
            {
                "title": decision.title,
                "source_url": decision.source_url,
                "external_id": decision.external_id,
                "authority": decision.court_name,
                "raw_text": decision.raw_text,
                "metadata": Jsonb(decision.metadata),
                "decision_date": decision.decision_date,
                "content_hash": decision.content_hash,
            },
        )
        legal_source_id = cursor.fetchone()[0]

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
            },
        )

        cursor.execute(_COUNT_CHUNKS, (legal_source_id,))
        chunk_count = cursor.fetchone()[0]

        if content_changed or chunk_count == 0:
            chunk_count = _write_chunks(cursor, legal_source_id, decision, max_chunk_chars)

        if existing is None:
            status: IngestStatus = "created"
        elif content_changed:
            status = "updated"
        else:
            status = "unchanged"

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
