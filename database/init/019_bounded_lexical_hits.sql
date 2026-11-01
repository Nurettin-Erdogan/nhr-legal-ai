\set ON_ERROR_STOP on

BEGIN;

-- Sınırlı aday sayılı sözcük araması. legal_rag_current_lexical_hits tüm eşleşen parçaları
-- sıralar; ~21M parçalı korpusta yaygın sözcüklerde (yüz binlerce eşleşme) soğuk diskte
-- 20-90 sn sürer. Bu sürüm eşleşmelerin ilk p_max_candidates tanesini (bitmap sırasıyla)
-- alıp yalnız onları sıralar: IO sınırlı ve süre öngörülebilir; kapsam kısmidir.
-- API yalnız tam sürüm zaman aşımına uğrarsa bunu kullanır.
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
            ls.metadata->>'verified_against_gazette' = 'true'
            AND ls.metadata->>'verified_against_mbs' = 'true'
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

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) TO nhr_runtime;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_bounded(tsquery, integer, integer) TO nhr_app;

COMMIT;
