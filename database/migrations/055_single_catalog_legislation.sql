\set ON_ERROR_STOP on

-- Mevzuatta tek resmî katalog yeter (kullanıcı kararı 2026-10-15, veri oturumu).
--
-- Önceden bir mevzuat maddesi ancak HEM Resmî Gazete HEM MBS (mevzuat.gov.tr) ile eşleştiğinde atıf alabiliyordu.
-- Artık ikisinden biriyle eşleşen madde `ingest_status = 'ready'` olur (ingestion/mevzuat/official_verify.py);
-- ikisiyle de eşleşmeyen maddeler silindi. Arama fonksiyonlarındaki koşul buna uyarlanır:
--   (verified_against_gazette AND verified_against_mbs)  ->  (verified_against_gazette OR verified_against_mbs)
-- Fonksiyon gövdelerinin geri kalanı canlı tanımla aynıdır (pg_get_functiondef). `ready` şartı ve toplu kararlar için
-- bulk_seed/pending ayrımı değişmez: doğrulanmamış mevzuat yine aranmaz.
--
-- İndeksler: çift doğrulama kısmi indeksi hiç kullanılmıyordu (idx_scan = 0), kaldırılır. Yürürlük indeksi sayım
-- sorgusunun koşuluyla aynı yeni koşulla kurulur. CONCURRENTLY: yazmaları kilitlemez, bu yüzden işlem bloğu yok.

-- legal_rag_current_lexical_hits: 1 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_current_lexical_hits(p_query tsquery, p_limit integer)
 RETURNS TABLE(chunk_id uuid, rank real)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
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
                OR ls.metadata->>'verified_against_mbs' = 'true')
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

-- legal_rag_current_lexical_hits_bounded: 1 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_current_lexical_hits_bounded(p_query tsquery, p_limit integer, p_max_candidates integer)
 RETURNS TABLE(chunk_id uuid, rank real)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
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
              OR ls.metadata->>'verified_against_mbs' = 'true'
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
$function$;

-- legal_rag_current_lexical_hits_official_bounded: 1 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_current_lexical_hits_official_bounded(p_query tsquery, p_limit integer, p_max_candidates integer)
 RETURNS TABLE(chunk_id uuid, rank real)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
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
            OR ls.metadata->>'verified_against_mbs' = 'true')
        OR ls.metadata->>'verified_text_against_mbs' = 'true'
      ))
      OR (ls.source_type = 'court_decision'
          AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending')
    )
  ORDER BY 2 DESC
  LIMIT p_limit
$function$;

-- legal_rag_current_lexical_hits_tiered: 2 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_current_lexical_hits_tiered(p_query tsquery, p_limit integer, p_seed_cap integer, p_official_cap integer DEFAULT 5000)
 RETURNS TABLE(chunk_id uuid, rank real, capped boolean)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
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
                  OR ls.metadata->>'verified_against_mbs' = 'true')
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
                  OR ls.metadata->>'verified_against_mbs' = 'true')
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

-- legal_rag_research_page: 1 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_research_page(p_query tsquery, p_limit integer, p_offset integer)
 RETURNS TABLE(source_id uuid, chunk_id uuid, rank real, total bigint)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
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
                    OR ls.metadata->>'verified_against_mbs' = 'true')
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
$function$;

-- legal_rag_research_page_bounded: 1 koşul
CREATE OR REPLACE FUNCTION public.legal_rag_research_page_bounded(p_query tsquery, p_filter tsquery, p_limit integer, p_offset integer, p_max_official integer, p_max_seed integer)
 RETURNS TABLE(source_id uuid, chunk_id uuid, rank real, total bigint, partial boolean)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
    WITH settings AS (
        SELECT greatest(0, least(coalesce(p_max_official, 0), 20000)) AS max_official,
               greatest(0, least(coalesce(p_max_seed, 0), 20000)) AS max_seed
    ),
    official_ids AS MATERIALIZED (
        -- Metin (search_vector) seçilmez: yalnız kimlik, dizin + yığın satırı yeter.
        SELECT chunk.id
        FROM public.legal_chunks chunk
        WHERE p_query IS NOT NULL AND numnode(p_query) > 0
          AND p_filter IS NOT NULL AND numnode(p_filter) > 0
          AND chunk.search_vector @@ p_filter
          AND chunk.embedding IS NOT NULL
        LIMIT (SELECT max_official + 1 FROM settings)
    ),
    seed_ids AS MATERIALIZED (
        SELECT chunk.id
        FROM public.legal_chunks chunk
        WHERE (SELECT max_seed FROM settings) > 0
          AND p_query IS NOT NULL AND numnode(p_query) > 0
          AND p_filter IS NOT NULL AND numnode(p_filter) > 0
          AND chunk.search_vector @@ p_filter
          AND chunk.embedding IS NULL
        LIMIT (SELECT max_seed + 1 FROM settings)
    ),
    state AS (
        SELECT ((SELECT count(*) FROM official_ids) > settings.max_official
                OR settings.max_seed = 0
                OR (SELECT count(*) FROM seed_ids) > settings.max_seed) AS partial
        FROM settings
    ),
    candidates AS (
        (SELECT official_ids.id, true AS official FROM official_ids LIMIT (SELECT max_official FROM settings))
        UNION ALL
        (SELECT seed_ids.id, false AS official FROM seed_ids LIMIT (SELECT max_seed FROM settings))
    ),
    ranked AS MATERIALIZED (
        -- Metin yalnız burada, sınırlı adaylar için açılır: ifade koşulu ve puan tam sorguyla (p_query).
        SELECT chunk.legal_source_id, chunk.id AS chunk_id, chunk.chunk_index, candidates.official,
               ts_rank_cd(chunk.search_vector, p_query)::real AS rank
        FROM candidates
        JOIN public.legal_chunks chunk ON chunk.id = candidates.id
        WHERE chunk.search_vector @@ p_query
    ),
    source_hits AS MATERIALIZED (
        SELECT DISTINCT ON (ranked.legal_source_id)
            ranked.legal_source_id AS source_id, ranked.chunk_id, ranked.rank,
            (ls.ingest_status = 'ready') AS verified
        FROM ranked
        JOIN public.legal_sources ls ON ls.id = ranked.legal_source_id
        WHERE ls.deleted_at IS NULL AND ls.is_current
          AND (
            (ls.ingest_status = 'ready' AND (
                ls.source_type <> 'legislation'
                OR (ls.metadata->>'verified_against_gazette' = 'true'
                    OR ls.metadata->>'verified_against_mbs' = 'true')
                OR ls.metadata->>'verified_text_against_mbs' = 'true'
            ))
            OR (ls.source_type = 'court_decision'
                AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending')
          )
        ORDER BY ranked.legal_source_id, ranked.official DESC, ranked.rank DESC, ranked.chunk_index, ranked.chunk_id
    )
    SELECT source_hits.source_id, source_hits.chunk_id, source_hits.rank,
           count(*) OVER () AS total, (SELECT state.partial FROM state)
    FROM source_hits
    -- Resmî doğrulanmış kaynaklar önce: sayfa yalnız doğrulanmış sonuçları gösterir; doğrulanmamış toplu kayıtlar
    -- ilk sayfaları doldurup sonucu boş bırakmasın (ör. "kaynak=2, doğrulama bekleyen=8").
    ORDER BY source_hits.verified DESC, source_hits.rank DESC, source_hits.source_id
    LIMIT greatest(1, least(p_limit, 51)) OFFSET greatest(0, p_offset)
$function$;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_legal_sources_legislation_effective_single
    ON legal_sources (effective_from, effective_to)
    WHERE source_type = 'legislation' AND deleted_at IS NULL AND ingest_status = 'ready'
      AND (metadata->>'verified_against_gazette' = 'true' OR metadata->>'verified_against_mbs' = 'true');
DROP INDEX CONCURRENTLY IF EXISTS idx_legal_sources_legislation_effective;
DROP INDEX CONCURRENTLY IF EXISTS idx_legal_sources_legislation_dual_verified;
