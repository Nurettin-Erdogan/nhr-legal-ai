\set ON_ERROR_STOP on

BEGIN;

CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits(
  p_query tsquery,
  p_limit integer
)
RETURNS TABLE (chunk_id uuid, rank real)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT chunk.id, ts_rank_cd(chunk.search_vector, p_query)::real
  FROM public.legal_chunks AS chunk
  JOIN public.legal_sources AS ls ON ls.id = chunk.legal_source_id
  WHERE p_query IS NOT NULL
    AND ls.deleted_at IS NULL
    AND ls.is_current
    AND (
      (
        ls.ingest_status = 'ready'
        AND (
          ls.source_type <> 'legislation'
          OR (
            (
              ls.metadata->>'verified_against_gazette' = 'true'
              AND ls.metadata->>'verified_against_mbs' = 'true'
            )
            OR ls.metadata->>'verified_text_against_mbs' = 'true'
          )
        )
      )
      OR (
        ls.ingestion_method = 'bulk_seed'
        AND ls.ingest_status = 'pending'
        AND ls.source_type = 'court_decision'
      )
    )
    AND chunk.search_vector @@ p_query
  ORDER BY 2 DESC
  LIMIT p_limit
$$;

CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits_bounded(
  p_query tsquery,
  p_limit integer,
  p_max_candidates integer
)
RETURNS TABLE (chunk_id uuid, rank real)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  WITH candidates AS MATERIALIZED (
    SELECT chunk.id, chunk.legal_source_id, chunk.search_vector
    FROM public.legal_chunks AS chunk
    WHERE p_query IS NOT NULL
      AND chunk.search_vector @@ p_query
    LIMIT p_max_candidates
  )
  SELECT candidates.id, ts_rank_cd(candidates.search_vector, p_query)::real
  FROM candidates
  JOIN public.legal_sources AS ls ON ls.id = candidates.legal_source_id
  WHERE ls.deleted_at IS NULL
    AND ls.is_current
    AND (
      (
        ls.ingest_status = 'ready'
        AND (
          ls.source_type <> 'legislation'
          OR (
            (
              ls.metadata->>'verified_against_gazette' = 'true'
              AND ls.metadata->>'verified_against_mbs' = 'true'
            )
            OR ls.metadata->>'verified_text_against_mbs' = 'true'
          )
        )
      )
      OR (
        ls.ingestion_method = 'bulk_seed'
        AND ls.ingest_status = 'pending'
        AND ls.source_type = 'court_decision'
      )
    )
  ORDER BY 2 DESC
  LIMIT p_limit
$$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) TO nhr_runtime;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) TO nhr_app;
REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) TO nhr_runtime;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) TO nhr_app;

COMMIT;
