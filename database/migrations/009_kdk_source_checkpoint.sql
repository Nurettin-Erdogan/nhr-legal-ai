\set ON_ERROR_STOP on

BEGIN;

INSERT INTO source_sync_checkpoints (source_name, health_state, health_detail)
VALUES (
  'kdk',
  'blocked',
  'PLANNED: KDK resmî karar portalı doğrulandı; ingestion sözleşmesi bekleniyor'
)
ON CONFLICT (source_name) DO UPDATE
SET health_state = EXCLUDED.health_state,
    health_detail = EXCLUDED.health_detail,
    updated_at = NOW();

COMMIT;
