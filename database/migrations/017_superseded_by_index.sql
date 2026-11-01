\set ON_ERROR_STOP on

BEGIN;

-- legal_sources.superseded_by_id, RESTRICT kısıtlı bir FK. İndeks olmadan her silme
-- (ör. toplu kayıt temizliği) tüm tabloyu tarar; milyonlarca satırda saatlerce sürer.
CREATE INDEX IF NOT EXISTS idx_legal_sources_superseded_by
  ON legal_sources (superseded_by_id)
  WHERE superseded_by_id IS NOT NULL;

COMMIT;
