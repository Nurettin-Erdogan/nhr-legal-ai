\set ON_ERROR_STOP on
BEGIN;

-- Keep full-corpus ranking, but do not read source metadata for every matching
-- chunk before selecting top results. OFFSET 0 fences preserve rank-first order.
-- This is NOT the old arbitrary first-N candidate fallback.
CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits(p_query tsquery, p_limit integer)
RETURNS TABLE (chunk_id uuid, rank real)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
BEGIN
  IF p_query IS NULL OR numnode(p_query) = 0 THEN
    RETURN;
  END IF;
  -- Replan with actual query selectivity instead of a generic tsquery estimate.
  -- SQL text is constant; user values are bound, never interpolated.
  RETURN QUERY EXECUTE $query$
    SELECT ranked.id, ranked.rank
    FROM (
      SELECT chunk.id, chunk.legal_source_id,
             ts_rank_cd(chunk.search_vector, $1)::real AS rank
      FROM public.legal_chunks chunk
      WHERE chunk.search_vector @@ $1
      ORDER BY rank DESC OFFSET 0
    ) ranked
    CROSS JOIN LATERAL (
      SELECT 1 FROM public.legal_sources ls
      WHERE ls.id = ranked.legal_source_id
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
      OFFSET 0
    ) eligible
    ORDER BY ranked.rank DESC
    LIMIT $2
  $query$ USING p_query, p_limit;
END;
$function$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) TO nhr_runtime, nhr_app;
COMMIT;
