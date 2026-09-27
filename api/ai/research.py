"""Public-corpus research pages, independent of the LLM context window.

No model, ingestion, verification queue or corpus writes. The public-corpus
function counts distinct sources before pagination, and only the selected page
is hydrated with full text. Never label a candidate count a total.
"""

from fastapi import APIRouter, HTTPException, Query
import psycopg

from api.ai.rag import RAGContext
from api.ai.retrieval import _SELECT_COLUMNS, _DETAIL_JOINS, _VERIFIED_SOURCE_FILTER
from api.ai.search_plan import plan_search, SEARCH_QUERY_SQL
from api.db import database_connection

router = APIRouter()

LEGACY_RESEARCH_SQL = f"""
WITH search_query AS ({SEARCH_QUERY_SQL}),
hits AS MATERIALIZED (
    SELECT hits.chunk_id, hits.rank FROM search_query
    CROSS JOIN LATERAL legal_rag_current_lexical_hits(search_query.value, NULL::integer) hits
    WHERE numnode(search_query.value) > 0
),
source_hits AS MATERIALIZED (
    -- The function already checks current/deleted/trust for this snapshot.
    -- Keep ONLY IDs through dedup/count/sort; hydrate large texts on the page.
    SELECT DISTINCT ON (chunk.legal_source_id)
        chunk.legal_source_id AS source_id, chunk.id AS chunk_id, hits.rank
    FROM hits
    JOIN legal_chunks chunk ON chunk.id = hits.chunk_id
    ORDER BY chunk.legal_source_id, hits.rank DESC, chunk.chunk_index, chunk.id
), page AS (
    SELECT *, count(*) OVER () AS total FROM source_hits
    ORDER BY rank DESC, source_id
    LIMIT %(limit)s OFFSET %(offset)s
)
SELECT {_SELECT_COLUMNS}, page.rank, page.total
FROM page
JOIN legal_chunks chunk ON chunk.id = page.chunk_id
JOIN legal_sources ls ON ls.id = page.source_id
{_DETAIL_JOINS}
WHERE ls.deleted_at IS NULL AND ls.is_current AND {_VERIFIED_SOURCE_FILTER}
ORDER BY page.rank DESC, page.source_id
"""

RESEARCH_SQL = f"""
WITH search_query AS ({SEARCH_QUERY_SQL}),
page AS MATERIALIZED (
    SELECT result.* FROM search_query
    CROSS JOIN LATERAL legal_rag_research_page(
        search_query.value, %(limit)s, %(offset)s
    ) result
)
SELECT {_SELECT_COLUMNS}, page.rank, page.total
FROM page
JOIN legal_chunks chunk ON chunk.id = page.chunk_id
JOIN legal_sources ls ON ls.id = page.source_id
{_DETAIL_JOINS}
WHERE ls.deleted_at IS NULL AND ls.is_current AND {_VERIFIED_SOURCE_FILTER}
ORDER BY page.rank DESC, page.source_id
"""


@router.get("/sources")
def research_sources(
    q: str = Query(min_length=5, max_length=2000),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    plan = plan_search(q)
    if not plan.text:
        raise HTTPException(422, "Arama için bir hukuki konu veya kavram yazın.")
    try:
        with database_connection() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '15s'")
            connection.execute("SET LOCAL work_mem = '32MB'")
            connection.execute("SET LOCAL max_parallel_workers_per_gather = 0")
            connection.execute("SET LOCAL jit = off")
            params = {
                "query": plan.text, "phrase": plan.phrase,
                "limit": limit + 1, "offset": offset,
            }
            try:
                with connection.transaction():
                    rows = connection.execute(RESEARCH_SQL, params).fetchall()
            except psycopg.errors.UndefinedFunction:
                # Rolling deployments can serve the old query until 027 is applied.
                rows = connection.execute(LEGACY_RESEARCH_SQL, params).fetchall()
    except psycopg.errors.QueryCanceled as exc:
        raise HTTPException(504, "Arama süresi doldu; tüm sonuçlar taranmış sayılmaz. Konuyu daraltıp yeniden deneyin.") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "Kaynak araması tamamlanamadı.") from exc
    has_more = len(rows) > limit
    total = int(rows[0]["total"]) if rows else (0 if offset == 0 else None)
    results = []
    for raw in rows[:limit]:
        row = dict(raw)
        row.pop("total")
        context = RAGContext(**row)
        results.append({
            "source_id": str(context.source_id), "reference": context.reference_line,
            "source_url": context.source_url, "verification": context.verification,
            "source_type": context.source_type, "excerpt": context.content,
        })
    return {
        "query": q, "search_text": plan.text, "required_phrase": plan.phrase,
        "scope": "searchable_current_corpus", "total": total,
        "has_more": has_more, "next_offset": offset + limit if has_more else None,
        "results": results,
    }
