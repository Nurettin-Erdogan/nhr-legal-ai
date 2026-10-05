\set ON_ERROR_STOP on

-- Pilot geri bildirimi: kullanıcının uygulama içinden gönderdiği hata/öneri/beğeni notları.
-- Kullanıcı yalnız kendi mesajlarını görür (RLS); pilotu yürüten kişi yönetici bağlantısıyla `scripts/list_feedback.py` ile okur.
-- Mesaja belge/sohbet içeriği otomatik eklenmez; yalnız kullanıcının yazdığı metin ve açık olduğu sayfa yolu saklanır.
BEGIN;

CREATE TABLE IF NOT EXISTS office_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL DEFAULT 'oneri' CHECK (category IN ('hata', 'oneri', 'begeni')),
  page TEXT CHECK (page IS NULL OR char_length(page) <= 200),
  message TEXT NOT NULL CHECK (char_length(message) BETWEEN 3 AND 4000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_office_feedback_owner ON office_feedback (owner_id, created_at DESC);

ALTER TABLE office_feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS office_feedback_owner_select ON office_feedback;
DROP POLICY IF EXISTS office_feedback_owner_insert ON office_feedback;
DROP POLICY IF EXISTS office_feedback_owner_delete ON office_feedback;
CREATE POLICY office_feedback_owner_select ON office_feedback FOR SELECT USING (owner_id = app_current_user_id());
CREATE POLICY office_feedback_owner_insert ON office_feedback FOR INSERT WITH CHECK (owner_id = app_current_user_id());
CREATE POLICY office_feedback_owner_delete ON office_feedback FOR DELETE USING (owner_id = app_current_user_id());
-- Güncelleme politikası yok: gönderilen geri bildirim değiştirilemez.

GRANT SELECT, INSERT, DELETE ON office_feedback TO nhr_runtime;

COMMIT;
