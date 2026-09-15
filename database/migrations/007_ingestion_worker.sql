\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE source_sync_runs
  ADD COLUMN IF NOT EXISTS records_quarantined INT NOT NULL DEFAULT 0
    CHECK (records_quarantined >= 0),
  ADD COLUMN IF NOT EXISTS requests_made INT NOT NULL DEFAULT 0
    CHECK (requests_made >= 0),
  ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0
    CHECK (retry_count >= 0),
  ADD COLUMN IF NOT EXISTS checkpoint_before JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS checkpoint_after JSONB,
  ADD COLUMN IF NOT EXISTS last_cursor JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE source_sync_runs DROP CONSTRAINT IF EXISTS source_sync_runs_status_check;
ALTER TABLE source_sync_runs ADD CONSTRAINT source_sync_runs_status_check
  CHECK (status IN (
    'queued', 'running', 'success', 'completed', 'partial', 'failed',
    'cancelled', 'captcha_required'
  ));

DROP POLICY IF EXISTS source_sync_runs_read ON source_sync_runs;
CREATE POLICY source_sync_runs_admin ON source_sync_runs FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE TABLE IF NOT EXISTS source_sync_checkpoints (
  source_name TEXT PRIMARY KEY,
  last_successful_sync_at TIMESTAMPTZ,
  last_attempt_at TIMESTAMPTZ,
  last_cursor JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_page INT,
  last_date_from DATE,
  last_date_to DATE,
  last_external_id TEXT,
  last_error TEXT,
  consecutive_failures INT NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  next_run_at TIMESTAMPTZ,
  health_state TEXT NOT NULL DEFAULT 'healthy'
    CHECK (health_state IN ('healthy', 'degraded', 'blocked', 'failed')),
  health_detail TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS source_coverage_windows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_name TEXT NOT NULL,
  date_from DATE NOT NULL,
  date_to DATE NOT NULL,
  chamber TEXT NOT NULL DEFAULT '',
  expected_count INT CHECK (expected_count IS NULL OR expected_count >= 0),
  seen_count INT NOT NULL DEFAULT 0 CHECK (seen_count >= 0),
  stored_count INT NOT NULL DEFAULT 0 CHECK (stored_count >= 0),
  duplicate_count INT NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
  failed_count INT NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
  complete BOOLEAN NOT NULL DEFAULT FALSE,
  completed_at TIMESTAMPTZ,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (source_name, date_from, date_to, chamber)
);
CREATE INDEX IF NOT EXISTS idx_source_coverage_incomplete
  ON source_coverage_windows (source_name, date_from)
  WHERE NOT complete;

ALTER TABLE source_sync_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_coverage_windows ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_sync_checkpoints_admin ON source_sync_checkpoints;
CREATE POLICY source_sync_checkpoints_admin ON source_sync_checkpoints FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

DROP POLICY IF EXISTS source_coverage_windows_admin ON source_coverage_windows;
CREATE POLICY source_coverage_windows_admin ON source_coverage_windows FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

GRANT SELECT, INSERT, UPDATE ON source_sync_checkpoints, source_coverage_windows,
  source_sync_runs, legal_source_quarantine TO nhr_runtime;

INSERT INTO source_sync_checkpoints (source_name, health_state, health_detail)
VALUES
  ('yargitay', 'healthy', 'ACTIVE: karararama.yargitay.gov.tr JSON/HTTP'),
  ('mevzuat', 'healthy', 'ACTIVE: bedesten.adalet.gov.tr/mevzuat'),
  ('danistay', 'blocked', 'PLANNED: resmi uç sözleşmesi doğrulanmadı'),
  ('aym', 'blocked', 'PLANNED: resmi uç sözleşmesi doğrulanmadı'),
  ('resmi_gazete', 'blocked', 'PLANNED: resmi uç sözleşmesi doğrulanmadı')
ON CONFLICT (source_name) DO NOTHING;

DROP INDEX IF EXISTS uq_court_decision_natural;
DROP INDEX IF EXISTS uq_legislation_details_version;

ALTER TABLE legal_sources
  ALTER COLUMN canonical_source_name SET DEFAULT 'Unspecified official source',
  ALTER COLUMN ingestion_method SET DEFAULT 'legacy_import',
  ALTER COLUMN fetched_at SET DEFAULT NOW(),
  ALTER COLUMN last_verified_at SET DEFAULT NOW(),
  ALTER COLUMN source_version SET DEFAULT '1';

COMMIT;
