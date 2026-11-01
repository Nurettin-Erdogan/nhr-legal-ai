\set ON_ERROR_STOP on

BEGIN;

INSERT INTO source_sync_checkpoints (source_name, health_state, health_detail)
VALUES (
  'resmi_gazete',
  'healthy',
  'VERIFICATION ACTIVE: Mevzuat tarih/sayı/numarası resmî arşivle çapraz doğrulanıyor; bağımsız korpus adapterı değil'
)
ON CONFLICT (source_name) DO UPDATE
SET health_state = EXCLUDED.health_state,
    health_detail = EXCLUDED.health_detail,
    updated_at = NOW();

COMMIT;
