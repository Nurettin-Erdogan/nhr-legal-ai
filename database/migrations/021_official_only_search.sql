\set ON_ERROR_STOP on

BEGIN;

-- Avukat araması ve asistan atıfı yalnız resmî doğrulanmış kayıtlardandır.
-- bulk_seed / pending üçüncü taraf derleme korpusta ve sayaçta durur; sonuç listesine girmez.

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
    AND ls.ingest_status = 'ready'
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
    SELECT chunk.id, chunk.search_vector
    FROM public.legal_chunks AS chunk
    JOIN public.legal_sources AS ls ON ls.id = chunk.legal_source_id
    WHERE p_query IS NOT NULL
      AND chunk.search_vector @@ p_query
      AND ls.deleted_at IS NULL
      AND ls.is_current
      AND ls.ingest_status = 'ready'
      AND (
        ls.source_type <> 'legislation'
        OR (
          ls.metadata->>'verified_against_gazette' = 'true'
          AND ls.metadata->>'verified_against_mbs' = 'true'
        )
      )
    LIMIT p_max_candidates
  )
  SELECT candidates.id, ts_rank_cd(candidates.search_vector, p_query)::real
  FROM candidates
  ORDER BY 2 DESC
  LIMIT p_limit
$$;

COMMIT;
