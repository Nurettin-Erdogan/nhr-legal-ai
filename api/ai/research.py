"""Public-corpus research pages, independent of the LLM context window.

No model or collector operations. On-demand official verification may promote
an exactly matched seed; pending records are never published. The public-corpus
function counts distinct sources before pagination, and only the selected page
is hydrated with full text. Never label a candidate count a total.

Broad topics ("kıdem tazminatı", "ihtiyati tedbir") match hundreds of thousands
of chunks; checking the phrase and ranking every one of them reads each chunk's
TOASTed tsvector and took >90 s on the live corpus (504 for the user). The page
therefore uses `legal_rag_research_page_bounded` (migration 037): candidates are
picked by index only and text is opened for a bounded number of them. Under the
caps the result is identical to the complete search; above them it is returned
with `partial = true`, the count is a lower bound and the UI says so.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
import psycopg

from api.auth.routes import current_user_id
from api.ai.rag import RAGContext
from api.ai.live_verify import verify_third_party_contexts
from api.ai.trust import verified_contexts
from api.ai.retrieval import _SELECT_COLUMNS, _DETAIL_JOINS, _VERIFIED_SOURCE_FILTER
from api.ai.search_plan import plan_search, SEARCH_QUERY_SQL
from api.ai.turkish_text import restore_turkish
from api.db import database_connection

router = APIRouter(dependencies=[Depends(current_user_id)])  # yalnız oturum açmış kullanıcı (erişim listesi)

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

# (resmî katman adayı, toplu katman adayı, süre) kademeleri: bir deneme zaman aşımına uğrarsa daha dar bir taramayla (toplu katman
# hiç taranmadan) yeniden denenir; hiçbiri yetmezse 504 (sahte boş/tam sonuç yok). Soğuk disk ve yazan arka plan işleri (embedding
# döngüsü) canlıda ilk denemeyi sık sık aşıyordu: son kademe küçük ama kısmi/işaretli bir sonuç döndürmeyi garanti etmeye yakındır.
RESEARCH_ATTEMPTS = ((2000, 1000, "9s"), (500, 0, "7s"), (120, 0, "5s"))

RESEARCH_SQL = f"""
WITH search_query AS ({SEARCH_QUERY_SQL}),
page AS MATERIALIZED (
    SELECT result.* FROM search_query
    CROSS JOIN LATERAL legal_rag_research_page_bounded(
        search_query.value, plainto_tsquery('turkish', %(query)s),
        %(limit)s, %(offset)s, %(max_official)s, %(max_seed)s
    ) result
)
SELECT {_SELECT_COLUMNS}, page.rank, page.total, page.partial
FROM page
JOIN legal_chunks chunk ON chunk.id = page.chunk_id
JOIN legal_sources ls ON ls.id = page.source_id
{_DETAIL_JOINS}
WHERE ls.deleted_at IS NULL AND ls.is_current AND {_VERIFIED_SOURCE_FILTER}
ORDER BY page.rank DESC, page.source_id
"""

# Migration 037 uygulanmamış veritabanı için: aday sınırı olmayan tam arama (yaygın konularda zaman aşımına uğrar).
COMPLETE_RESEARCH_SQL = f"""
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


def _run_research(connection, params):
    """Sınırlı arama (önce geniş, zaman aşımında dar); 037 yoksa tam arama, o da yoksa 027 öncesi sorgu."""
    timed_out = None
    for max_official, max_seed, timeout in RESEARCH_ATTEMPTS:
        try:
            with connection.transaction():
                connection.execute(f"SET LOCAL statement_timeout = '{timeout}'")
                return connection.execute(
                    RESEARCH_SQL, {**params, "max_official": max_official, "max_seed": max_seed}
                ).fetchall()
        except psycopg.errors.QueryCanceled as exc:
            timed_out = exc
        except psycopg.errors.UndefinedFunction:
            break  # rolling deployment: 037 not applied yet
    if timed_out is not None:
        raise timed_out
    try:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout = '15s'")
            return connection.execute(COMPLETE_RESEARCH_SQL, params).fetchall()
    except psycopg.errors.UndefinedFunction:
        # Rolling deployments can serve the old query until 027 is applied.
        return connection.execute(LEGACY_RESEARCH_SQL, params).fetchall()


def load_candidate_page(q: str, limit: int, offset: int):
    """Read-only candidate retrieval; not a publishable list of evidence."""
    plan = plan_search(q)
    if not plan.text:
        raise HTTPException(422, "Arama için bir hukuki konu veya kavram yazın.")
    try:
        with database_connection() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL work_mem = '32MB'")
            connection.execute("SET LOCAL max_parallel_workers_per_gather = 0")
            connection.execute("SET LOCAL jit = off")
            params = {
                "query": plan.text, "phrase": plan.phrase,
                "limit": limit + 1, "offset": offset,
            }
            rows = _run_research(connection, params)
    except psycopg.errors.QueryCanceled as exc:
        raise HTTPException(504, "Arama süresi doldu; tüm sonuçlar taranmış sayılmaz. Konuyu daraltıp yeniden deneyin.") from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "Kaynak araması tamamlanamadı.") from exc
    has_more = len(rows) > limit
    candidate_total = int(rows[0]["total"]) if rows else (0 if offset == 0 else None)
    # Sınırlı tarama: toplam "en az" sayıdır ve bazı eşleşmeler hiç taranmamış olabilir.
    partial = bool(rows[0].get("partial")) if rows else False
    candidates = []
    for raw in rows[:limit]:
        row = dict(raw)
        row.pop("total")
        row.pop("partial", None)
        candidates.append(RAGContext(**row))
    return plan, candidates, has_more, candidate_total, partial


@router.get("/sources")
def research_sources(
    q: str = Query(min_length=5, max_length=2000),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    # ASCII yazılmış soru için aksanlar yalnız arama metninde geri getirilir (`query` yazıldığı gibi döner).
    plan, candidates, has_more, candidate_total, partial = load_candidate_page(restore_turkish(q), limit, offset)
    try:
        contexts = verified_contexts(verify_third_party_contexts(candidates))
    except Exception:
        # Already verified records can still be shown; failures never bless seeds.
        contexts = verified_contexts(candidates)
    results = []
    for context in contexts:
        results.append({
            "source_id": str(context.source_id), "reference": context.reference_line,
            "source_url": context.source_url, "verification": context.verification,
            "source_type": context.source_type, "excerpt": context.content,
        })
    return {
        "query": q, "search_text": plan.text, "required_phrase": plan.phrase,
        "scope": "verified_current_corpus",
        # The SQL count includes candidates, not yet verified matches. Never
        # display it as the number of officially verified results.
        "total": 0 if candidate_total == 0 else None,
        "candidate_total": candidate_total,
        # true: konu çok geniş, adayların bir kısmı tarandı; candidate_total "en az" sayıdır, liste eksik olabilir.
        "partial": partial,
        "verification_pending": len(candidates) - len(contexts),
        "has_more": has_more, "next_offset": offset + limit if has_more else None,
        "results": results,
    }
