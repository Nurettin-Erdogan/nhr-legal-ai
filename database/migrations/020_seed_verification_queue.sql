\set ON_ERROR_STOP on

BEGIN;

-- Atıf yapılan üçüncü taraf kararların öncelikli doğrulama kuyruğu.
-- Cevapta bir `bulk_seed` kaydına atıf yapıldığında satır eklenir; `scripts/verify_seeds.py`
-- her turda önce bu kuyruğu boşaltır, sonra tarih sırasına döner. Böylece portalı yoran tek
-- bir süreç kalır (eşzamanlı istek yok, CAPTCHA riski artmaz) ama kullanılan kararlar
-- önce doğrulanır.
CREATE TABLE IF NOT EXISTS seed_verification_queue (
  legal_source_id uuid PRIMARY KEY REFERENCES legal_sources(id) ON DELETE CASCADE,
  requested_at timestamptz NOT NULL DEFAULT now(),
  request_count integer NOT NULL DEFAULT 1,
  picked_at timestamptz
);

-- Sıra: çok istenen önce, eşitlikte en eski istek önce.
CREATE INDEX IF NOT EXISTS idx_seed_verification_queue_order
  ON seed_verification_queue (request_count DESC, requested_at)
  WHERE picked_at IS NULL;

ALTER TABLE seed_verification_queue ENABLE ROW LEVEL SECURITY;

-- Kuyruk kullanıcıya ait veri taşımaz (yalnız kaynak kimliği); uygulama rolü ekler ve okur,
-- doğrulayıcı (admin rolü) tüketir.
DROP POLICY IF EXISTS seed_verification_queue_runtime ON seed_verification_queue;
CREATE POLICY seed_verification_queue_runtime ON seed_verification_queue
  FOR ALL TO nhr_runtime USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON seed_verification_queue TO nhr_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON seed_verification_queue TO nhr_app;

COMMIT;
