\set ON_ERROR_STOP on
-- Önceden hazırlanmış, kaynaklarıyla doğrulanmış cevaplar (2026-10-31).
--
-- Amaç: sık sorulan genel hukuk sorularına arama ve model çağrısı olmadan anında cevap. Satırı yalnız `scripts/warm_answer_cache.py`
-- (nhr_app) yazar; uygulama (nhr_runtime) yalnız okur. Satırda KULLANICI VERİSİ YOKTUR: soru metni elle hazırlanmış listeden gelir,
-- cevap yalnız genel hukuk kaynaklarına dayanır. Canlı trafikten hiçbir soru bu tabloya yazılmaz.
--
-- Geçerlilik: bir satır, atıf yaptığı parçaların ŞU ANKİ durumu (sürüm, revizyon, içerik özeti) kayıt anındakiyle aynıysa ve parçalar
-- hâlâ resmî-doğrulanmış-güncel süzgeçlerinden geçiyorsa kullanılır (`api/ai/warm_cache.py`). Mevzuat değişirse satır kendiliğinden
-- geçersiz olur; yanlış cevap dönmez. `pipeline_version` cevap üretim mantığı değiştiğinde yükseltilir ve eski satırları devre dışı bırakır.
BEGIN;
CREATE TABLE IF NOT EXISTS public.verified_answer_cache (
  question_key TEXT NOT NULL,
  pipeline_version TEXT NOT NULL,
  question_text TEXT NOT NULL,
  answer_text TEXT NOT NULL,
  answer_kind TEXT NOT NULL DEFAULT 'legal',
  contexts JSONB NOT NULL,
  source_fingerprint TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (question_key, pipeline_version)
);
ALTER TABLE public.verified_answer_cache ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS verified_answer_cache_select ON public.verified_answer_cache;
CREATE POLICY verified_answer_cache_select ON public.verified_answer_cache FOR SELECT USING (true);
REVOKE ALL ON public.verified_answer_cache FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nhr_runtime') THEN
    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.verified_answer_cache FROM nhr_runtime;
    GRANT SELECT ON public.verified_answer_cache TO nhr_runtime;
  END IF;
END $$;
COMMIT;
