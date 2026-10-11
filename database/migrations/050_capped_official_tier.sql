\set ON_ERROR_STOP on

-- Katmanlı sözcük aramasında resmî katmana da üst sınır.
--
-- Ölçüldü (2026-10-08): resmî katman eşleşen HER parçayı puanlıyordu. Çok sözcüklü aramalarda eşleşme
-- 50-5 000 parçadır ve sorun olmaz; yaygın tek sözcükte ise resmî katmanda "tazminat" 492 070, "itirazın
-- iptali icra inkar tazminatı" 54 291 parçayla eşleşir. Hepsini puanlamak 12-39 sn sürdü; "tazminat"
-- araması 35 sn bekletip 504 verdi, "kira" 13 sn, "icra takibi" 16 sn sürdü. Doğrulanmış korpus büyüdükçe
-- bu süre de büyür.
--
-- Değişenler:
--   1. p_official_cap (varsayılan 5 000): resmî katmanda en çok bu kadar eşleşme puanlanır. Eşleşme
--      sınırın altındaysa (olağan arama) katman yine TAM puanlanır; aşılırsa `capped` = true döner ve
--      arayüz sonucu "kısmi" diye işaretler. p_official_cap <= 0 sınırı kaldırır (eski davranış).
--   2. Toplu katmanda uygunluk denetimi artık resmî katmandaki gibi puan sırasıyla ve yalnız gerektiği
--      kadar yapılır. Önceden taranan 5 000 parçanın hepsi kaynak tablosuyla birleştiriliyordu; aynı
--      sorguda dokunulan sayfa ~60 000'den ~37 000'e indi. Sonuç kümesi değişmez.
--   3. Puan taramada hesaplanır; CTE'ye yalnız kimlik ve puan taşınır.
--
-- Uygunluk koşulu legal_rag_current_lexical_hits ile aynıdır: doğrulanmamış kayıt yine aranır ve ayrı
-- gösterilir, doğrulanmamış mevzuat aranmaz. Üç parametreli çağrılar varsayılan sınırla çalışmaya devam eder.

BEGIN;

DROP FUNCTION IF EXISTS legal_rag_current_lexical_hits_tiered(tsquery, integer, integer);

CREATE OR REPLACE FUNCTION legal_rag_current_lexical_hits_tiered(
  p_query tsquery,
  p_limit integer,
  p_seed_cap integer,
  p_official_cap integer DEFAULT 5000
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
    WITH official_raw AS MATERIALIZED (
      SELECT chunk.id, chunk.legal_source_id,
             ts_rank_cd(chunk.search_vector, $1)::real AS rank
      FROM public.legal_chunks chunk
      WHERE chunk.search_vector @@ $1
        AND chunk.embedding IS NOT NULL
      LIMIT CASE WHEN $4 > 0 THEN $4 + 1 END
    ),
    official AS (
      SELECT ranked.id, ranked.rank
      FROM (
        SELECT scanned.id, scanned.legal_source_id, scanned.rank
        FROM (SELECT * FROM official_raw LIMIT CASE WHEN $4 > 0 THEN $4 END) scanned
        ORDER BY scanned.rank DESC OFFSET 0
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
      SELECT chunk.id, chunk.legal_source_id,
             ts_rank_cd(chunk.search_vector, $1)::real AS rank
      FROM public.legal_chunks chunk
      WHERE $3 > 0
        AND chunk.search_vector @@ $1
        AND chunk.embedding IS NULL
      LIMIT $3 + 1
    ),
    tier_state AS (
      -- p_seed_cap = 0: toplu katman hiç taranmadı (yalnız resmî sonuç); yine "kısmi" sayılır.
      SELECT ($3 = 0
              OR (SELECT count(*) FROM seed_raw) > $3
              OR ($4 > 0 AND (SELECT count(*) FROM official_raw) > $4)) AS capped
    ),
    seeds AS (
      SELECT ranked.id, ranked.rank
      FROM (
        SELECT scanned.id, scanned.legal_source_id, scanned.rank
        FROM (SELECT * FROM seed_raw LIMIT $3) scanned
        ORDER BY scanned.rank DESC OFFSET 0
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
    )
    SELECT merged.id, merged.rank, (SELECT tier_state.capped FROM tier_state)
    FROM (
      SELECT official.id, official.rank FROM official
      UNION ALL
      SELECT seeds.id, seeds.rank FROM seeds
    ) merged
    ORDER BY merged.rank DESC
    LIMIT $2
  $query$ USING p_query, p_limit, p_seed_cap, p_official_cap;
END;
$function$;

REVOKE ALL ON FUNCTION legal_rag_current_lexical_hits_tiered(tsquery, integer, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_current_lexical_hits_tiered(tsquery, integer, integer, integer) TO nhr_runtime, nhr_app;

COMMIT;
