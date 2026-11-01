\set ON_ERROR_STOP on
BEGIN;

-- UYAP eklenti anahtarı artık düz saklanmaz: yalnız SHA-256 özeti ve gösterim için ilk 9 karakter.
-- İstemci anahtarı üretir ve ekler; tetikleyici düz değeri özetleyip siler. Özet bir kez kaydedilince
-- değiştirilemez (anahtar yenilemek = eskisini `revoked` yapıp yenisini eklemek).
ALTER TABLE office_uyap_ingest_tokens ADD COLUMN IF NOT EXISTS token_hash TEXT;
ALTER TABLE office_uyap_ingest_tokens ADD COLUMN IF NOT EXISTS token_prefix TEXT;
ALTER TABLE office_uyap_ingest_tokens ALTER COLUMN token DROP NOT NULL;

-- Var olan anahtarlar çalışmaya devam eder (eklentideki değer aynı kalır); düz değer silinir.
UPDATE office_uyap_ingest_tokens
SET token_hash = encode(sha256(convert_to(token, 'UTF8')), 'hex'),
    token_prefix = left(token, 9)
WHERE token IS NOT NULL AND token_hash IS NULL;
UPDATE office_uyap_ingest_tokens SET token = NULL WHERE token_hash IS NOT NULL;

ALTER TABLE office_uyap_ingest_tokens ALTER COLUMN token_hash SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_office_uyap_tokens_hash ON office_uyap_ingest_tokens (token_hash);

CREATE OR REPLACE FUNCTION office_uyap_token_hash_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.token IS NULL OR char_length(NEW.token) < 32 THEN
      RAISE EXCEPTION 'UYAP anahtarı en az 32 karakter olmalı' USING ERRCODE = '22023';
    END IF;
    NEW.token_hash := encode(sha256(convert_to(NEW.token, 'UTF8')), 'hex');
    NEW.token_prefix := left(NEW.token, 9);
    NEW.token := NULL;
  ELSE
    -- Anahtar değeri sonradan değiştirilemez ya da geri okunabilir hâle getirilemez.
    IF NEW.token IS NOT NULL
       OR NEW.token_hash IS DISTINCT FROM OLD.token_hash
       OR NEW.token_prefix IS DISTINCT FROM OLD.token_prefix THEN
      RAISE EXCEPTION 'UYAP anahtarı değiştirilemez; yenisini oluşturun' USING ERRCODE = '22023';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_office_uyap_token_hash_guard ON office_uyap_ingest_tokens;
CREATE TRIGGER trg_office_uyap_token_hash_guard
  BEFORE INSERT OR UPDATE ON office_uyap_ingest_tokens
  FOR EACH ROW EXECUTE FUNCTION office_uyap_token_hash_guard();

COMMENT ON COLUMN office_uyap_ingest_tokens.token IS 'Her zaman NULL: düz anahtar saklanmaz (token_hash kullanılır).';
COMMIT;
