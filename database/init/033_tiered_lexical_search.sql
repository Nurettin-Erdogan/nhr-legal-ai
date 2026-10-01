\set ON_ERROR_STOP on

-- Katmanlı sözcük araması.
--
-- legal_rag_current_lexical_hits eşleşen HER parçayı ts_rank_cd ile puanlar; bunun için her
-- parçanın tsvector'ü (TOAST) okunur. ~28M parçalık korpusta yaygın sözcüklerde yüz binlerce
-- rastgele okuma demektir ve sanallaştırılmış diskte soğuk sorgu 10-40 sn sürer.
--
-- Bu fonksiyon korpusu ikiye ayırır:
--   1. Resmî katman (embedding IS NOT NULL, ~2,4M parça): küçük kısmi GIN dizinini
--      (idx_legal_chunks_search_vector_official) kullanır ve TAM puanlanır.
--   2. Doğrulanmamış toplu katman (embedding IS NULL): eşleşmelerin ilk p_seed_cap tanesi
--      puanlanır; sınır aşıldıysa `capped` = true döner ve arayüz sonucu "kısmi" diye işaretler.
--      p_seed_cap = 0 bu katmanı hiç taramaz (zaman aşımı yedeği) ve her zaman capped = true döner.
--
-- Doğrulanmamış kayıtlar yine aranabilir ve ayrı gösterilir; burada yalnız tarama kapsamı sınırlanır.
-- Uygunluk koşulu legal_rag_current_lexical_hits ile aynıdır.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_legal_chunks_search_vector_official
  ON public.legal_chunks USING gin (search_vector)
  WHERE embedding IS NOT NULL;

BEGIN;

CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits_tiered(
  p_query tsquery,
  p_limit integer,
  p_seed_cap integer
)
RETURNS TABLE (chunk_id uuid, rank real, capped boolean)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
BEGIN
  IF p_query IS NULL OR numnode(p_query) = 0 THEN
    RETURN;
  END IF;
  -- SQL metni sabit; kullanıcı değerleri bağlanır, birleştirilmez.
  RETURN QUERY EXECUTE $query$
    WITH official AS (
      SELECT ranked.id, ranked.rank
      FROM (
        SELECT chunk.id, chunk.legal_source_id,
               ts_rank_cd(chunk.search_vector, $1)::real AS rank
        FROM public.legal_chunks chunk
        WHERE chunk.search_vector @@ $1
          AND chunk.embedding IS NOT NULL
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
    ),
    seed_raw AS MATERIALIZED (
      SELECT chunk.id, chunk.legal_source_id, chunk.search_vector
      FROM public.legal_chunks chunk
      WHERE $3 > 0
        AND chunk.search_vector @@ $1
        AND chunk.embedding IS NULL
      LIMIT $3 + 1
    ),
    seed_state AS (
      -- p_seed_cap = 0: toplu katman hiç taranmadı (yalnız resmî sonuç); yine "kısmi" sayılır.
      SELECT ($3 = 0 OR count(*) > $3) AS capped FROM seed_raw
    ),
    seeds AS (
      SELECT scanned.id, ts_rank_cd(scanned.search_vector, $1)::real AS rank
      FROM (SELECT * FROM seed_raw LIMIT $3) scanned
      JOIN public.legal_sources ls ON ls.id = scanned.legal_source_id
      WHERE ls.deleted_at IS NULL AND ls.is_current
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
      ORDER BY 2 DESC
      LIMIT $2
    )
    SELECT merged.id, merged.rank, (SELECT seed_state.capped FROM seed_state)
    FROM (
      SELECT official.id, official.rank FROM official
      UNION ALL
      SELECT seeds.id, seeds.rank FROM seeds
    ) merged
    ORDER BY merged.rank DESC
    LIMIT $2
  $query$ USING p_query, p_limit, p_seed_cap;
END;
$function$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits_tiered(tsquery, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_tiered(tsquery, integer, integer) TO nhr_runtime, nhr_app;

-- Geniş (VEYA) yedek arama: "haksız | fesih | ihbar | tazminat" gibi sorgular yüz binlerce resmî
-- parçayla eşleşir; hepsini puanlamak 30 sn sürer. Bu sürüm yalnız resmî katmanda (kısmi GIN dizini)
-- eşleşmelerin ilk p_max_candidates tanesini puanlar; sonuç her zaman kısmidir. Yalnız AND sorgusu
-- sonuç vermediğinde kullanılır.
CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits_official_bounded(
  p_query tsquery,
  p_limit integer,
  p_max_candidates integer
)
RETURNS TABLE (chunk_id uuid, rank real)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  WITH candidates AS MATERIALIZED (
    SELECT chunk.id, chunk.legal_source_id, chunk.search_vector
    FROM public.legal_chunks AS chunk
    WHERE p_query IS NOT NULL
      AND chunk.search_vector @@ p_query
      AND chunk.embedding IS NOT NULL
    LIMIT p_max_candidates
  )
  SELECT candidates.id, ts_rank_cd(candidates.search_vector, p_query)::real
  FROM candidates
  JOIN public.legal_sources AS ls ON ls.id = candidates.legal_source_id
  WHERE ls.deleted_at IS NULL
    AND ls.is_current
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
  ORDER BY 2 DESC
  LIMIT p_limit
$$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits_official_bounded(tsquery, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_official_bounded(tsquery, integer, integer) TO nhr_runtime, nhr_app;
COMMIT;
