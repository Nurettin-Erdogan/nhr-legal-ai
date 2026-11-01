\set ON_ERROR_STOP on
BEGIN;
-- Korpus panel sayaçları (kullanıcı kararı 2026-10-21: "tablo anlık güncellenmiyor, kalıcı çözüm yap").
--
-- Sorun: panel sayıları legal_sources üzerinde count(*) ile hesaplanıyordu. nhr_runtime ile RLS yüzünden bu sayım yük altında
-- 10-15 dakika sürüyor (bazen zaman aşımı), API her 10 dakikada bir tekrar çalıştırıp diski dolduruyor ve sayfa eski sayıyı
-- gösteriyordu. Çözüm: sayılar tarama olmadan, değişiklikte artımlı tutulur.
--
--   corpus_counters        : taban sayımlar (anahtar -> adet). Yalnız corpus_counters_rebuild()/compact() yazar.
--   corpus_counter_deltas  : satır tetikleyicilerinin eklediği +1/-1 farkları. Yalnız EKLEME yapıldığı için eşzamanlı
--                            işçiler (hub'ın paralel yazıcıları) tek bir sayaç satırında kilit beklemez.
--   corpus_counts()        : taban + fark toplamı; ucuz (fark tablosu her hub turunda katlanır). SECURITY DEFINER:
--                            nhr_runtime tablolara doğrudan erişmez, RLS maliyeti de ödenmez.
--
-- Sayılan kayıt = silinmemiş + güncel + 'ready' (mevzuatta ayrıca resmî katalogla doğrulanmış). Doğrulanmamış toplu kayıtlar
-- ('pending') sayılmaz: uygulamada gösterilen sayı, gösterilebilen kayıt sayısıdır.
-- Anahtarlar: 'src|<source_type>|<authority>' ve 'chunks|embedded' (embedding'i hazır parça sayısı).
--
-- Güvenlik: tablolar ve işlevler nhr_app'e aittir; nhr_runtime yalnız corpus_counts() çalıştırabilir (toplu sayılar,
-- kullanıcı verisi içermez). Tetikleyici işlevleri SECURITY DEFINER'dır (çağıran rolden bağımsız çalışır).

CREATE TABLE IF NOT EXISTS public.corpus_counters (
  key TEXT PRIMARY KEY,
  n BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS public.corpus_counter_deltas (
  key TEXT NOT NULL,
  delta SMALLINT NOT NULL CHECK (delta IN (-1, 1))
);
REVOKE ALL ON public.corpus_counters, public.corpus_counter_deltas FROM PUBLIC;

-- Kaydın hangi sayaca girdiği (NULL = sayılmaz). Tetikleyici ve yeniden kurma aynı ifadeyi kullanır.
CREATE OR REPLACE FUNCTION public.corpus_counter_key(
  p_source_type text, p_authority text, p_deleted_at timestamptz, p_is_current boolean,
  p_ingest_status text, p_metadata jsonb)
 RETURNS text
 LANGUAGE sql
 IMMUTABLE PARALLEL SAFE
 SET search_path TO 'pg_catalog'
AS $function$
  SELECT CASE
    WHEN p_deleted_at IS NULL AND p_is_current AND p_ingest_status = 'ready'
         AND (p_source_type <> 'legislation'
              OR p_metadata->>'verified_against_gazette' = 'true'
              OR p_metadata->>'verified_against_mbs' = 'true')
    THEN 'src|' || p_source_type || '|' || coalesce(p_authority, '')
  END
$function$;

CREATE OR REPLACE FUNCTION public.corpus_counter_sources_trg()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  old_key text;
  new_key text;
BEGIN
  -- Sayaç bakımı asıl yazmayı asla bozmamalı: hata olursa yutulur (kayma, bir sonraki yeniden kurmada düzelir).
  BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
      old_key := public.corpus_counter_key(OLD.source_type, OLD.authority, OLD.deleted_at, OLD.is_current, OLD.ingest_status, OLD.metadata);
    END IF;
    IF TG_OP IN ('UPDATE', 'INSERT') THEN
      new_key := public.corpus_counter_key(NEW.source_type, NEW.authority, NEW.deleted_at, NEW.is_current, NEW.ingest_status, NEW.metadata);
    END IF;
    IF old_key IS DISTINCT FROM new_key THEN
      IF old_key IS NOT NULL THEN
        INSERT INTO public.corpus_counter_deltas(key, delta) VALUES (old_key, -1);
      END IF;
      IF new_key IS NOT NULL THEN
        INSERT INTO public.corpus_counter_deltas(key, delta) VALUES (new_key, 1);
      END IF;
    END IF;
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'corpus_counter_sources_trg: %', SQLERRM;
  END;
  RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION public.corpus_counter_chunks_trg()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  BEGIN
    IF TG_OP = 'DELETE' THEN
      IF OLD.embedding IS NOT NULL THEN
        INSERT INTO public.corpus_counter_deltas(key, delta) VALUES ('chunks|embedded', -1);
      END IF;
    ELSIF TG_OP = 'INSERT' THEN
      IF NEW.embedding IS NOT NULL THEN
        INSERT INTO public.corpus_counter_deltas(key, delta) VALUES ('chunks|embedded', 1);
      END IF;
    ELSIF (OLD.embedding IS NULL) <> (NEW.embedding IS NULL) THEN
      INSERT INTO public.corpus_counter_deltas(key, delta)
      VALUES ('chunks|embedded', CASE WHEN NEW.embedding IS NULL THEN -1 ELSE 1 END);
    END IF;
  EXCEPTION WHEN OTHERS THEN
    RAISE WARNING 'corpus_counter_chunks_trg: %', SQLERRM;
  END;
  RETURN NULL;
END;
$function$;

-- Yalnız ilgili sütunlar değişince (UPDATE OF) ve sayaç anahtarı değiştiğinde çalışır: hub'ın metin yazan güncellemeleri
-- ya da updated_at tetikleyicisi fazladan iş çıkarmaz.
DROP TRIGGER IF EXISTS legal_sources_corpus_counter_ins ON public.legal_sources;
DROP TRIGGER IF EXISTS legal_sources_corpus_counter_upd ON public.legal_sources;
DROP TRIGGER IF EXISTS legal_sources_corpus_counter_del ON public.legal_sources;
CREATE TRIGGER legal_sources_corpus_counter_ins AFTER INSERT ON public.legal_sources
  FOR EACH ROW WHEN (public.corpus_counter_key(NEW.source_type, NEW.authority, NEW.deleted_at, NEW.is_current, NEW.ingest_status, NEW.metadata) IS NOT NULL)
  EXECUTE FUNCTION public.corpus_counter_sources_trg();
CREATE TRIGGER legal_sources_corpus_counter_upd AFTER UPDATE OF source_type, authority, deleted_at, is_current, ingest_status, metadata ON public.legal_sources
  FOR EACH ROW WHEN (
    public.corpus_counter_key(OLD.source_type, OLD.authority, OLD.deleted_at, OLD.is_current, OLD.ingest_status, OLD.metadata)
    IS DISTINCT FROM
    public.corpus_counter_key(NEW.source_type, NEW.authority, NEW.deleted_at, NEW.is_current, NEW.ingest_status, NEW.metadata))
  EXECUTE FUNCTION public.corpus_counter_sources_trg();
CREATE TRIGGER legal_sources_corpus_counter_del AFTER DELETE ON public.legal_sources
  FOR EACH ROW WHEN (public.corpus_counter_key(OLD.source_type, OLD.authority, OLD.deleted_at, OLD.is_current, OLD.ingest_status, OLD.metadata) IS NOT NULL)
  EXECUTE FUNCTION public.corpus_counter_sources_trg();

DROP TRIGGER IF EXISTS legal_chunks_corpus_counter_ins ON public.legal_chunks;
DROP TRIGGER IF EXISTS legal_chunks_corpus_counter_upd ON public.legal_chunks;
DROP TRIGGER IF EXISTS legal_chunks_corpus_counter_del ON public.legal_chunks;
CREATE TRIGGER legal_chunks_corpus_counter_ins AFTER INSERT ON public.legal_chunks
  FOR EACH ROW WHEN (NEW.embedding IS NOT NULL) EXECUTE FUNCTION public.corpus_counter_chunks_trg();
CREATE TRIGGER legal_chunks_corpus_counter_upd AFTER UPDATE OF embedding ON public.legal_chunks
  FOR EACH ROW WHEN ((OLD.embedding IS NULL) <> (NEW.embedding IS NULL)) EXECUTE FUNCTION public.corpus_counter_chunks_trg();
CREATE TRIGGER legal_chunks_corpus_counter_del AFTER DELETE ON public.legal_chunks
  FOR EACH ROW WHEN (OLD.embedding IS NOT NULL) EXECUTE FUNCTION public.corpus_counter_chunks_trg();

-- Güncel sayılar: taban + henüz katlanmamış farklar. Taban yoksa (rebuild hiç çalışmadıysa) satır döndürmez.
CREATE OR REPLACE FUNCTION public.corpus_counts()
 RETURNS TABLE(key text, n bigint)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
  SELECT b.key, b.n + coalesce(d.s, 0)
  FROM public.corpus_counters b
  LEFT JOIN (SELECT key, sum(delta)::bigint AS s FROM public.corpus_counter_deltas GROUP BY key) d USING (key)
  UNION ALL
  SELECT d.key, d.s FROM (SELECT key, sum(delta)::bigint AS s FROM public.corpus_counter_deltas GROUP BY key) d
  WHERE NOT EXISTS (SELECT 1 FROM public.corpus_counters b WHERE b.key = d.key)
    AND EXISTS (SELECT 1 FROM public.corpus_counters)
$function$;

-- Fark satırlarını tabana katlar (hub her turdan sonra çağırır). Silinen farklar aynı ifadede tabana eklenir: atomik.
CREATE OR REPLACE FUNCTION public.corpus_counters_compact()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  folded integer;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.corpus_counters) THEN
    RETURN 0;  -- taban kurulmadan farklar katlanmaz
  END IF;
  WITH gone AS (
    DELETE FROM public.corpus_counter_deltas RETURNING key, delta
  ), summed AS (
    SELECT key, sum(delta)::bigint AS s, count(*)::integer AS c FROM gone GROUP BY key
  ), upserted AS (
    INSERT INTO public.corpus_counters AS t(key, n)
    SELECT key, s FROM summed
    ON CONFLICT (key) DO UPDATE SET n = t.n + excluded.n
    RETURNING 1
  )
  SELECT coalesce(sum(c), 0)::integer INTO folded FROM summed;
  RETURN folded;
END;
$function$;

-- Tabanı baştan sayar (ilk kurulum ve kayma düzeltmesi). REPEATABLE READ işlemde çağrılmalıdır: sayım anındaki anlık
-- görüntüye girmiş farklar silinir (tabanda zaten var), sonradan işlenenler kalır ve eklenir; çifte sayım olmaz.
-- Örnek: BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT corpus_counters_rebuild(); COMMIT;
CREATE OR REPLACE FUNCTION public.corpus_counters_rebuild()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  IF current_setting('transaction_isolation') <> 'repeatable read' THEN
    RAISE EXCEPTION 'corpus_counters_rebuild yalnız REPEATABLE READ işlemde çağrılabilir';
  END IF;
  SET LOCAL statement_timeout = 0;
  DELETE FROM public.corpus_counter_deltas;
  DELETE FROM public.corpus_counters;
  INSERT INTO public.corpus_counters(key, n)
  SELECT key, count(*)
  FROM (
    SELECT public.corpus_counter_key(ls.source_type, ls.authority, ls.deleted_at, ls.is_current, ls.ingest_status, ls.metadata) AS key
    FROM public.legal_sources ls
  ) t
  WHERE key IS NOT NULL
  GROUP BY key;
  INSERT INTO public.corpus_counters(key, n)
  SELECT 'chunks|embedded', count(*) FROM public.legal_chunks WHERE embedding IS NOT NULL;
END;
$function$;

REVOKE ALL ON FUNCTION public.corpus_counts(), public.corpus_counters_compact(), public.corpus_counters_rebuild() FROM PUBLIC;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nhr_runtime') THEN
    GRANT EXECUTE ON FUNCTION public.corpus_counts() TO nhr_runtime;
  END IF;
END $$;
COMMIT;
