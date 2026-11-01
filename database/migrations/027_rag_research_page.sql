\set ON_ERROR_STOP on
BEGIN;

-- Public legal corpus ONLY; never reads documents, users or project tables.
-- Avoid per-hit RLS subqueries and fetching TOAST text before pagination.
-- No candidate cap: totals are distinct matching current sources, not top-K.
CREATE OR REPLACE FUNCTION legal_rag_research_page(
    p_query tsquery, p_limit integer, p_offset integer
)
RETURNS TABLE (source_id uuid, chunk_id uuid, rank real, total bigint)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    WITH source_hits AS MATERIALIZED (
        SELECT DISTINCT ON (ls.id)
            ls.id AS source_id, chunk.id AS chunk_id,
            ts_rank_cd(chunk.search_vector, p_query)::real AS rank
        FROM public.legal_chunks chunk
        JOIN public.legal_sources ls ON ls.id = chunk.legal_source_id
        WHERE p_query IS NOT NULL AND numnode(p_query) > 0
          AND chunk.search_vector @@ p_query
          AND ls.deleted_at IS NULL AND ls.is_current
          AND (
            (ls.ingest_status = 'ready' AND (
                ls.source_type <> 'legislation'
                OR (ls.metadata->>'verified_against_gazette' = 'true'
                    AND ls.metadata->>'verified_against_mbs' = 'true')
                OR ls.metadata->>'verified_text_against_mbs' = 'true'
            ))
            OR (ls.source_type = 'court_decision'
                AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending')
          )
        ORDER BY ls.id, rank DESC, chunk.chunk_index, chunk.id
    )
    SELECT source_hits.*, count(*) OVER ()
    FROM source_hits
    ORDER BY rank DESC, source_id
    LIMIT greatest(1, least(p_limit, 51)) OFFSET greatest(0, p_offset)
$$;
REVOKE ALL ON FUNCTION legal_rag_research_page(tsquery, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_research_page(tsquery, integer, integer) TO nhr_runtime, nhr_app;
COMMIT;
