from __future__ import annotations

from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query

from api.db import database_connection
from api.schemas import CorpusStats, LegalSearchResponse, LegalSourceDetail

router = APIRouter(prefix="/api/legal", tags=["legal"])

_SEARCH_SQL = """
WITH search_query AS (
    SELECT plainto_tsquery('turkish', %(query)s) AS value
),
ranked AS (
    SELECT DISTINCT ON (ls.id)
        ls.id,
        ls.title,
        ls.source_url,
        details.chamber,
        details.docket_no,
        details.decision_no,
        details.decision_date,
        left(chunk.content, 700) AS excerpt,
        ts_rank_cd(chunk.search_vector, search_query.value) AS rank
    FROM legal_sources ls
    JOIN court_decision_details details ON details.legal_source_id = ls.id
    JOIN legal_chunks chunk ON chunk.legal_source_id = ls.id
    CROSS JOIN search_query
    WHERE ls.source_type = 'court_decision'
      AND ls.deleted_at IS NULL
      AND chunk.search_vector @@ search_query.value
    ORDER BY ls.id, rank DESC, chunk.chunk_index
)
SELECT ranked.*, count(*) OVER () AS total
FROM ranked
ORDER BY rank DESC, decision_date DESC NULLS LAST, title
LIMIT %(limit)s OFFSET %(offset)s
"""

_DETAIL_SQL = """
SELECT
    ls.id,
    ls.title,
    ls.source_url,
    ls.external_id,
    ls.authority,
    details.chamber,
    details.docket_no,
    details.decision_no,
    details.decision_date,
    COALESCE(ls.raw_text, '') AS raw_text,
    ls.metadata
FROM legal_sources ls
JOIN court_decision_details details ON details.legal_source_id = ls.id
WHERE ls.id = %s
  AND ls.source_type = 'court_decision'
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
                    max(details.decision_date) AS latest_decision_date
                FROM legal_sources ls
                JOIN court_decision_details details ON details.legal_source_id = ls.id
                LEFT JOIN legal_chunks chunk ON chunk.legal_source_id = ls.id
                WHERE ls.source_type = 'court_decision' AND ls.deleted_at IS NULL
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
) -> LegalSearchResponse:
    query = " ".join(q.split())
    try:
        with database_connection() as connection:
            rows = connection.execute(
                _SEARCH_SQL,
                {"query": query, "limit": limit, "offset": offset},
            ).fetchall()
    except psycopg.Error as exc:
        raise _database_unavailable(exc) from exc

    total = int(rows[0]["total"]) if rows else 0
    results = [dict(row) for row in rows]
    for result in results:
        result.pop("total", None)
    return LegalSearchResponse(
        query=query,
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
                raise HTTPException(status_code=404, detail="Karar bulunamadı")
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
