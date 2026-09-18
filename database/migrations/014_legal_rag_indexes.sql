\set ON_ERROR_STOP on

BEGIN;

-- Current, citation-eligible sources used by lexical RAG.
CREATE INDEX IF NOT EXISTS idx_legal_sources_rag_current
  ON legal_sources (id)
  WHERE deleted_at IS NULL
    AND ingest_status = 'ready'
    AND is_current;

CREATE INDEX IF NOT EXISTS idx_legal_sources_legislation_dual_verified
  ON legal_sources (id)
  WHERE source_type = 'legislation'
    AND deleted_at IS NULL
    AND ingest_status = 'ready'
    AND (metadata->>'verified_against_gazette') = 'true'
    AND (metadata->>'verified_against_mbs') = 'true';

CREATE INDEX IF NOT EXISTS idx_legal_sources_legislation_effective
  ON legal_sources (effective_from, effective_to)
  WHERE source_type = 'legislation'
    AND deleted_at IS NULL
    AND ingest_status = 'ready'
    AND (metadata->>'verified_against_gazette') = 'true'
    AND (metadata->>'verified_against_mbs') = 'true';

-- SECURITY DEFINER FTS helper: RLS on legal_chunks wraps every row in a
-- correlated source lookup and prevents the GIN index from being used.
-- The predicate is stricter than the SELECT policy (ready + current +
-- dual-verified legislation) so unverified mevzuat still cannot enter RAG.
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
    AND ls.ingest_status = 'ready'
    AND ls.is_current
    AND (
      ls.source_type <> 'legislation'
      OR (
        ls.metadata->>'verified_against_gazette' = 'true'
        AND ls.metadata->>'verified_against_mbs' = 'true'
      )
    )
    AND chunk.search_vector @@ p_query
  ORDER BY 2 DESC
  LIMIT p_limit
$$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) TO nhr_runtime;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits(tsquery, integer) TO nhr_app;

COMMIT;
