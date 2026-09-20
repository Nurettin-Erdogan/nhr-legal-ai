\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS bulk_seed_inventory (
  document_id TEXT PRIMARY KEY,
  source_dataset TEXT NOT NULL,
  court_hint TEXT,
  chamber TEXT,
  docket_no TEXT,
  decision_no TEXT,
  decision_date DATE,
  has_fulltext BOOLEAN NOT NULL DEFAULT FALSE,
  text_length INT NOT NULL DEFAULT 0 CHECK (text_length >= 0),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bulk_seed_inventory_fulltext
  ON bulk_seed_inventory (has_fulltext);
CREATE INDEX IF NOT EXISTS idx_bulk_seed_inventory_natural
  ON bulk_seed_inventory (docket_no, decision_no);

CREATE TABLE IF NOT EXISTS bulk_seed_fulltext_queue (
  document_id TEXT PRIMARY KEY
    REFERENCES bulk_seed_inventory(document_id) ON DELETE CASCADE,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'in_progress', 'done', 'skipped', 'failed')),
  attempts INT NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  last_error TEXT,
  next_run_at TIMESTAMPTZ,
  checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bulk_seed_fulltext_queue_due
  ON bulk_seed_fulltext_queue (status, next_run_at)
  WHERE status IN ('pending', 'failed');

ALTER TABLE bulk_seed_inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulk_seed_fulltext_queue ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS bulk_seed_inventory_admin ON bulk_seed_inventory;
CREATE POLICY bulk_seed_inventory_admin ON bulk_seed_inventory FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

DROP POLICY IF EXISTS bulk_seed_fulltext_queue_admin ON bulk_seed_fulltext_queue;
CREATE POLICY bulk_seed_fulltext_queue_admin ON bulk_seed_fulltext_queue FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE INDEX IF NOT EXISTS idx_court_decision_docket_decision
  ON court_decision_details (docket_no, decision_no)
  WHERE is_current AND docket_no IS NOT NULL AND decision_no IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_legal_sources_current_content_hash
  ON legal_sources (content_hash)
  WHERE is_current AND deleted_at IS NULL AND content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_legal_sources_ready_stats
  ON legal_sources (source_type, authority, published_at)
  WHERE deleted_at IS NULL AND ingest_status = 'ready' AND is_current;

GRANT SELECT ON bulk_seed_inventory, bulk_seed_fulltext_queue TO nhr_runtime;

COMMIT;
