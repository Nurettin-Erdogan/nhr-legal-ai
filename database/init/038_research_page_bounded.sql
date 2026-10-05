\set ON_ERROR_STOP on

-- Araştırma sayfası (/api/ai/sources) için sınırlı adaylı arama.
--
-- legal_rag_research_page eşleşen HER parçanın tsvector'ünü açar (TOAST): hem ifade denetimi ("kıdem tazminatı"
-- gibi bilinen ifadelerde kelimelerin yan yana olması) hem ts_rank_cd bunu gerektirir. Yaygın konularda bu yüz
-- binlerce rastgele okuma demek; canlı korpusta (2026-10-04) "kıdem tazminatı", "ihtiyati tedbir", "işe iade",
-- "tapu iptal tescil" 90 sn'de bitmedi, API 15 sn'de kesip 504 veriyordu.
--
-- Bu fonksiyon adayları önce YALNIZ dizinle seçer (p_filter: ifadesiz AND sorgusu; GIN bunu metin açmadan
-- yanıtlar), metni yalnız sınırlı sayıda aday için açar (ifade denetimi + puanlama):
--   * resmî katman (embedding IS NOT NULL, kısmi GIN dizini): ilk p_max_official aday,
--   * toplu/doğrulanmamış katman (embedding IS NULL): ilk p_max_seed aday (0 = hiç taranmaz).
-- Adaylar sınırların altındaysa sonuç legal_rag_research_page ile aynıdır ve partial = false döner.
-- Sınır aşıldıysa partial = true: toplam "en az" sayılır, arayüz sonucu kısmi diye gösterir ve konuyu daraltmayı
-- önerir (sessizce eksik liste "tam" diye sunulmaz). Uygunluk koşulu legal_rag_research_page ile aynıdır.
-- Sıralama: önce resmî doğrulanmış (ingest_status = 'ready'), sonra puan; böylece sayfalar doğrulanmış sonuçlarla dolar.

BEGIN;

CREATE OR REPLACE FUNCTION legal_rag_research_page_bounded(
    p_query tsquery, p_filter tsquery, p_limit integer, p_offset integer,
    p_max_official integer, p_max_seed integer
)
RETURNS TABLE (source_id uuid, chunk_id uuid, rank real, total bigint, partial boolean)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
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
                    AND ls.metadata->>'verified_against_mbs' = 'true')
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
$$;

REVOKE ALL ON FUNCTION legal_rag_research_page_bounded(tsquery, tsquery, integer, integer, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION legal_rag_research_page_bounded(tsquery, tsquery, integer, integer, integer, integer) TO nhr_runtime, nhr_app;

COMMIT;
