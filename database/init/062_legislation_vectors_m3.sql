\set ON_ERROR_STOP on
-- Mevzuat anlam araması için ikinci, Türkçe'de güçlü gömme modeli (bge-m3, 1024 boyut) — 2026-10-22.
--
-- Ölçüm (18 soru, doğru madde 4.025 mevzuat parçası arasında): ilk 5'te bulunan — nomic-embed-text 12/18, qwen3-embedding
-- 16/18, bge-m3 17/18. nomic "Ücret alacağında faiz hangi tarihten itibaren işler?" sorusunda İş K. m. 34'ü 217., çek ibraz
-- süresini 3485. sıraya koyuyordu. Yalnız 109 bin mevzuat parçası yeniden vektörlenir; karar vektörlerine dokunulmaz.
--
-- `embedding_m3` boş olabilir: `scripts/embed_legislation_m3.py` doldurur (yalnız nhr_app yazar). Parçanın asıl vektörü
-- (nomic) değişince — metin değişti demektir — tetikleyici `embedding_m3`'ü boşaltır; eski metnin vektörü kalmaz. Arama, m3
-- vektörü olmayan parçalar için eski kolu kullanmaya devam eder.

BEGIN;
ALTER TABLE public.legislation_chunk_vectors ADD COLUMN IF NOT EXISTS embedding_m3 vector(1024);

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
          embedding = EXCLUDED.embedding,
          -- New text (re-embedded chunk): the second-model vector of the old text must not survive.
          embedding_m3 = CASE WHEN legislation_chunk_vectors.embedding IS DISTINCT FROM EXCLUDED.embedding
                              THEN NULL ELSE legislation_chunk_vectors.embedding_m3 END;
  END IF;
  RETURN NULL;
END;
$function$;
REVOKE ALL ON FUNCTION public.sync_legislation_chunk_vector() FROM PUBLIC;
COMMIT;

SET max_parallel_maintenance_workers = 0;
SET maintenance_work_mem = '1GB';
CREATE INDEX IF NOT EXISTS idx_legislation_chunk_vectors_m3_hnsw
  ON public.legislation_chunk_vectors USING hnsw (embedding_m3 vector_cosine_ops)
  WHERE embedding_m3 IS NOT NULL;
RESET maintenance_work_mem;
RESET max_parallel_maintenance_workers;
