from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query

from api.db import database_connection
from api.schemas import CorpusStats, LegalSearchResponse, LegalSourceDetail

router = APIRouter(prefix="/api/legal", tags=["legal"])

_SEARCH_SQL = """
WITH search_query AS (
    SELECT to_tsquery(
        'turkish',
        array_to_string(
            tsvector_to_array(to_tsvector('turkish', %(query)s)),
            ' | '
        )
    ) AS value
),
ranked AS (
    SELECT DISTINCT ON (ls.id)
        ls.id,
        ls.source_type,
        ls.title,
        ls.source_url,
        ls.authority,
        decision.court_name,
        decision.chamber,
        decision.docket_no,
        decision.decision_no,
        decision.decision_date,
        legislation.legislation_type,
        legislation.law_name,
        legislation.law_no,
        legislation.article_no,
        legislation.article_title,
        legislation.official_gazette_date,
        legislation.version_date,
        ls.effective_from,
        ls.effective_to,
        ls.source_version,
        ls.revision,
        left(chunk.content, 700) AS excerpt,
        ts_rank_cd(chunk.search_vector, search_query.value) AS rank
    FROM legal_sources ls
    LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
    LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
    JOIN legal_chunks chunk ON chunk.legal_source_id = ls.id
    CROSS JOIN search_query
    WHERE ls.source_type IN ('court_decision', 'legislation')
      AND ls.deleted_at IS NULL
      AND (
          (CAST(%(as_of)s AS date) IS NULL AND ls.is_current)
          OR (
              CAST(%(as_of)s AS date) IS NOT NULL
              AND (
                  (
                      ls.source_type = 'legislation'
                      AND ls.effective_from IS NOT NULL
                      AND ls.effective_from <= CAST(%(as_of)s AS date)
                      AND (
                          ls.effective_to IS NULL
                          OR ls.effective_to >= CAST(%(as_of)s AS date)
                      )
                  )
                  OR (
                      ls.source_type = 'court_decision'
                      AND ls.is_current
                      AND decision.decision_date IS NOT NULL
                      AND decision.decision_date <= CAST(%(as_of)s AS date)
                  )
              )
          )
      )
      AND search_query.value IS NOT NULL
      AND chunk.search_vector @@ search_query.value
    ORDER BY ls.id, rank DESC, chunk.chunk_index
)
SELECT ranked.*, count(*) OVER () AS total
FROM ranked
ORDER BY rank DESC,
         COALESCE(decision_date, official_gazette_date, version_date) DESC NULLS LAST,
         title
LIMIT %(limit)s OFFSET %(offset)s
"""

_DETAIL_SQL = """
SELECT
    ls.id,
    ls.source_type,
    ls.title,
    ls.source_url,
    ls.external_id,
    ls.authority,
    decision.court_name,
    decision.chamber,
    decision.docket_no,
    decision.decision_no,
    decision.decision_date,
    legislation.legislation_type,
    legislation.law_name,
    legislation.law_no,
    legislation.article_no,
    legislation.article_title,
    legislation.official_gazette_no,
    legislation.official_gazette_date,
    legislation.version_date,
    ls.effective_from,
    ls.effective_to,
    ls.canonical_source_name,
    ls.official_source_url,
    ls.ingestion_method,
    ls.fetched_at,
    ls.last_verified_at,
    ls.content_hash,
    ls.source_version,
    ls.revision,
    ls.is_current,
    ls.superseded_by_id,
    COALESCE(ls.raw_text, '') AS raw_text,
    ls.metadata
FROM legal_sources ls
LEFT JOIN court_decision_details decision ON decision.legal_source_id = ls.id
LEFT JOIN legislation_details legislation ON legislation.legal_source_id = ls.id
WHERE ls.id = %s
  AND ls.source_type IN ('court_decision', 'legislation')
  AND ls.deleted_at IS NULL
"""


def _database_unavailable(exc: psycopg.Error) -> HTTPException:
    return HTTPException(status_code=503, detail="Hukuk veritabanına şu anda ulaşılamıyor")


@router.get("/stats", response_model=CorpusStats)
def corpus_stats() -> CorpusStats:
    try:
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT
                    count(DISTINCT ls.id)::int AS source_count,
                    count(chunk.id)::int AS chunk_count,
                    count(DISTINCT ls.id) FILTER (
                        WHERE ls.source_type = 'court_decision'
                    )::int AS decision_count,
                    count(DISTINCT ls.id) FILTER (
                        WHERE ls.source_type = 'legislation'
                    )::int AS legislation_count,
                    max(details.decision_date) AS latest_decision_date
                FROM legal_sources ls
                LEFT JOIN court_decision_details details ON details.legal_source_id = ls.id
                LEFT JOIN legal_chunks chunk ON chunk.legal_source_id = ls.id
                WHERE ls.source_type IN ('court_decision', 'legislation')
                  AND ls.deleted_at IS NULL
                  AND ls.is_current
                """
            ).fetchone()
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc
    return CorpusStats(**row)


@router.get("/search", response_model=LegalSearchResponse)
def search_legal_sources(
    q: str = Query(min_length=2, max_length=300),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    as_of: date | None = None,
) -> LegalSearchResponse:
    query = " ".join(q.split())
    try:
        with database_connection() as connection:
            rows = connection.execute(
                _SEARCH_SQL,
                {"query": query, "limit": limit, "offset": offset, "as_of": as_of},
            ).fetchall()
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc

    total = int(rows[0]["total"]) if rows else 0
    results = [dict(row) for row in rows]
    for result in results:
        result.pop("total", None)
    return LegalSearchResponse(
        query=query,
        as_of=as_of,
        total=total,
        limit=limit,
        offset=offset,
        results=results,
    )


@router.get("/sources/{source_id}", response_model=LegalSourceDetail)
def legal_source_detail(source_id: UUID) -> LegalSourceDetail:
    try:
        with database_connection() as connection:
            source = connection.execute(_DETAIL_SQL, (source_id,)).fetchone()
            if source is None:
                raise HTTPException(status_code=404, detail="Hukuk kaynağı bulunamadı")
            chunks = connection.execute(
                """
                SELECT id, chunk_index, content
                FROM legal_chunks
                WHERE legal_source_id = %s
                ORDER BY chunk_index
                """,
                (source_id,),
            ).fetchall()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc

    return LegalSourceDetail(**source, chunks=chunks)
