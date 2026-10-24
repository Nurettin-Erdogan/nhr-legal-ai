\set ON_ERROR_STOP on
-- Mevzuat için ayrı anlam araması (2026-10-22).
--
-- Sorun: anlam araması tek bir HNSW dizininde 7,8 M parça vektörünü tarar; mevzuat bunun %1,4'üdür (109 bin parça). Genel
-- bir soruda ("Haksız fiilden doğan tazminat davası ne zaman zamanaşımına uğrar?") en yakın 40-50 aday hep mahkeme kararı
-- oluyor ve asıl madde (TBK m. 72) hiç aday olmuyordu. Ortak dizinde `source_type = 'legislation'` süzgeciyle aramak 20-60
-- sn'de bitmedi (süzgeç dizinde değil, birleştirmede uygulanıyor).
--
-- Çözüm: mevzuat parçalarının vektörleri ayrı, küçük bir tabloda kendi HNSW dizinine sahip. Tablo bir KOPYADIR; doğruluk
-- kaynağı yine legal_chunks/legal_sources'tır. Arama sorgusu sonuçları legal_sources'a geri bağlayıp aynı resmî/güncel/sürüm
-- süzgeçlerinden geçirir; kopyada eski bir satır kalsa bile gösterilmez.
--
-- Eşitleme: legal_chunks üzerinde vektör değişince çalışan tetikleyici (yalnız mevzuat parçası kopyalanır; karar parçasında
-- tek bir birincil anahtar araması yapar). İlk doldurma bu dosyada; tetikleyici, büyük tabloyu dizin kurulurken kilitlememek
-- için ayrı bir işlemde kurulur ve aradaki değişiklikler ikinci doldurmayla yakalanır.
--
-- Güvenlik: tablo ve işlevler nhr_app'e aittir. nhr_runtime yalnız okur (RLS: silinmemiş kaynak ya da yönetici; legal_chunks
-- ile aynı kural). Yazma yalnız SECURITY DEFINER tetikleyici işlevinden olur.

BEGIN;
CREATE TABLE IF NOT EXISTS public.legislation_chunk_vectors (
  chunk_id UUID PRIMARY KEY REFERENCES public.legal_chunks(id) ON DELETE CASCADE,
  legal_source_id UUID NOT NULL REFERENCES public.legal_sources(id) ON DELETE CASCADE,
  embedding_model TEXT NOT NULL,
  embedding vector(768) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_legislation_chunk_vectors_source ON public.legislation_chunk_vectors (legal_source_id);

ALTER TABLE public.legislation_chunk_vectors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS legislation_chunk_vectors_select ON public.legislation_chunk_vectors;
CREATE POLICY legislation_chunk_vectors_select ON public.legislation_chunk_vectors FOR SELECT USING (
  EXISTS (
    SELECT 1 FROM public.legal_sources AS source
    WHERE source.id = legal_source_id AND (source.deleted_at IS NULL OR app_has_global_role('admin'))
  )
);
REVOKE ALL ON public.legislation_chunk_vectors FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.legislation_chunk_vectors FROM nhr_runtime;
    GRANT SELECT ON public.legislation_chunk_vectors TO nhr_runtime;
  END IF;
END $$;

INSERT INTO public.legislation_chunk_vectors (chunk_id, legal_source_id, embedding_model, embedding)
SELECT chunk.id, chunk.legal_source_id, COALESCE(chunk.embedding_model, ''), chunk.embedding
FROM public.legal_sources AS source
JOIN public.legal_chunks AS chunk ON chunk.legal_source_id = source.id
WHERE source.source_type = 'legislation' AND chunk.embedding IS NOT NULL AND vector_dims(chunk.embedding) = 768
ON CONFLICT (chunk_id) DO NOTHING;
COMMIT;

-- Paralel kurulum Docker'ın küçük /dev/shm alanında çöküyor (2026-09-26 HNSW deneyimi): seri kur.
SET max_parallel_maintenance_workers = 0;
SET maintenance_work_mem = '1GB';
CREATE INDEX IF NOT EXISTS idx_legislation_chunk_vectors_hnsw
  ON public.legislation_chunk_vectors USING hnsw (embedding vector_cosine_ops);
RESET maintenance_work_mem;
RESET max_parallel_maintenance_workers;

BEGIN;
CREATE OR REPLACE FUNCTION public.sync_legislation_chunk_vector()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  -- A vector of another size (test fixtures, a future model) is never copied, and never blocks the chunk write.
  IF NEW.embedding IS NULL OR vector_dims(NEW.embedding) <> 768 THEN
    DELETE FROM public.legislation_chunk_vectors WHERE chunk_id = NEW.id;
  ELSIF EXISTS (
    SELECT 1 FROM public.legal_sources AS source
    WHERE source.id = NEW.legal_source_id AND source.source_type = 'legislation'
  ) THEN
    INSERT INTO public.legislation_chunk_vectors (chunk_id, legal_source_id, embedding_model, embedding)
    VALUES (NEW.id, NEW.legal_source_id, COALESCE(NEW.embedding_model, ''), NEW.embedding)
    ON CONFLICT (chunk_id) DO UPDATE
      SET legal_source_id = EXCLUDED.legal_source_id,
          embedding_model = EXCLUDED.embedding_model,
          embedding = EXCLUDED.embedding;
  END IF;
  RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.sync_legislation_chunk_vector() FROM PUBLIC;

DROP TRIGGER IF EXISTS legal_chunks_legislation_vector_insert ON public.legal_chunks;
CREATE TRIGGER legal_chunks_legislation_vector_insert
  AFTER INSERT ON public.legal_chunks
  FOR EACH ROW WHEN (NEW.embedding IS NOT NULL)
  EXECUTE FUNCTION public.sync_legislation_chunk_vector();

DROP TRIGGER IF EXISTS legal_chunks_legislation_vector_update ON public.legal_chunks;
CREATE TRIGGER legal_chunks_legislation_vector_update
  AFTER UPDATE OF embedding, embedding_model ON public.legal_chunks
  FOR EACH ROW WHEN (OLD.embedding IS DISTINCT FROM NEW.embedding
                     OR OLD.embedding_model IS DISTINCT FROM NEW.embedding_model)
  EXECUTE FUNCTION public.sync_legislation_chunk_vector();

-- İlk doldurma ile tetikleyici arasında vektörü değişen mevzuat parçaları.
INSERT INTO public.legislation_chunk_vectors (chunk_id, legal_source_id, embedding_model, embedding)
SELECT chunk.id, chunk.legal_source_id, COALESCE(chunk.embedding_model, ''), chunk.embedding
FROM public.legal_sources AS source
JOIN public.legal_chunks AS chunk ON chunk.legal_source_id = source.id
WHERE source.source_type = 'legislation' AND chunk.embedding IS NOT NULL AND vector_dims(chunk.embedding) = 768
ON CONFLICT (chunk_id) DO UPDATE
  SET legal_source_id = EXCLUDED.legal_source_id,
      embedding_model = EXCLUDED.embedding_model,
      embedding = EXCLUDED.embedding
  WHERE legislation_chunk_vectors.embedding IS DISTINCT FROM EXCLUDED.embedding
     OR legislation_chunk_vectors.embedding_model IS DISTINCT FROM EXCLUDED.embedding_model;
COMMIT;
ANALYZE public.legislation_chunk_vectors;
