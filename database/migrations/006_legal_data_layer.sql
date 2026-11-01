\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE legal_sources
  ADD COLUMN canonical_source_name TEXT,
  ADD COLUMN official_source_url TEXT,
  ADD COLUMN ingestion_method TEXT,
  ADD COLUMN fetched_at TIMESTAMPTZ,
  ADD COLUMN last_verified_at TIMESTAMPTZ,
  ADD COLUMN source_version TEXT,
  ADD COLUMN revision INT NOT NULL DEFAULT 1,
  ADD COLUMN is_current BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN superseded_by_id UUID REFERENCES legal_sources(id) ON DELETE RESTRICT,
  ADD CONSTRAINT legal_sources_revision_check CHECK (revision > 0),
  ADD CONSTRAINT legal_sources_not_self_superseded_check
    CHECK (superseded_by_id IS NULL OR superseded_by_id <> id);

UPDATE legal_sources
SET canonical_source_name = CASE source_type
      WHEN 'court_decision' THEN 'Yargıtay Karar Arama'
      WHEN 'legislation' THEN 'Mevzuat Bilgi Sistemi'
      ELSE COALESCE(authority, title)
    END,
    official_source_url = source_url,
    ingestion_method = CASE source_type
      WHEN 'court_decision' THEN 'yargitay_public_json_http'
      WHEN 'legislation' THEN 'bedesten_public_json_http'
      ELSE 'legacy_import'
    END,
    fetched_at = COALESCE(last_ingested_at, updated_at, created_at),
    last_verified_at = COALESCE(last_ingested_at, updated_at, created_at),
    source_version = COALESCE(version_label, '1');

ALTER TABLE legal_sources
  ALTER COLUMN canonical_source_name SET NOT NULL,
  ALTER COLUMN canonical_source_name SET DEFAULT 'Unspecified official source',
  ALTER COLUMN ingestion_method SET NOT NULL,
  ALTER COLUMN ingestion_method SET DEFAULT 'legacy_import',
  ALTER COLUMN fetched_at SET NOT NULL,
  ALTER COLUMN fetched_at SET DEFAULT NOW(),
  ALTER COLUMN last_verified_at SET NOT NULL,
  ALTER COLUMN last_verified_at SET DEFAULT NOW(),
  ALTER COLUMN source_version SET NOT NULL,
  ALTER COLUMN source_version SET DEFAULT '1';

DROP INDEX uq_legal_sources_external_id;
CREATE UNIQUE INDEX uq_legal_sources_current_external_id
  ON legal_sources (source_type, external_id)
  WHERE external_id IS NOT NULL AND is_current;
CREATE INDEX idx_legal_sources_version_history
  ON legal_sources (source_type, external_id, revision DESC)
  WHERE external_id IS NOT NULL;
CREATE INDEX idx_legal_sources_effective_period
  ON legal_sources (effective_from, effective_to)
  WHERE is_current AND deleted_at IS NULL;

DROP INDEX uq_legislation_details_version;
DROP INDEX uq_court_decision_natural;
CREATE INDEX idx_legislation_details_identity_lookup
  ON legislation_details (legislation_type, law_no, article_no, version_date DESC);
CREATE INDEX idx_court_decision_natural_lookup
  ON court_decision_details (
    lower(court_name), lower(COALESCE(chamber, '')), docket_no, decision_no
  );

CREATE TABLE legislation_identities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legislation_type TEXT NOT NULL,
  law_no TEXT NOT NULL,
  article_no TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  jurisdiction TEXT NOT NULL DEFAULT 'TR',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (legislation_type, law_no, article_no)
);

INSERT INTO legislation_identities (
  legislation_type, law_no, article_no, canonical_name
)
SELECT DISTINCT ON (legislation_type, law_no, article_no)
  legislation_type,
  law_no,
  article_no,
  law_name
FROM legislation_details
WHERE law_no IS NOT NULL AND btrim(law_no) <> ''
  AND article_no IS NOT NULL AND btrim(article_no) <> ''
ORDER BY legislation_type, law_no, article_no, updated_at DESC;

ALTER TABLE legislation_details
  ADD COLUMN legislation_identity_id UUID
    REFERENCES legislation_identities(id) ON DELETE RESTRICT,
  ADD COLUMN version_identity TEXT,
  ADD COLUMN amendment_source TEXT;

UPDATE legislation_details AS detail
SET legislation_identity_id = identity.id,
    version_identity = COALESCE(
      detail.version_date::text,
      source.content_hash,
      'legacy:' || detail.legal_source_id::text
    )
FROM legislation_identities AS identity,
     legal_sources AS source
WHERE identity.legislation_type = detail.legislation_type
  AND identity.law_no = detail.law_no
  AND identity.article_no = detail.article_no
  AND source.id = detail.legal_source_id;

SET CONSTRAINTS ALL IMMEDIATE;

CREATE UNIQUE INDEX uq_legislation_identity_version
  ON legislation_details (legislation_identity_id, version_identity)
  WHERE legislation_identity_id IS NOT NULL AND version_identity IS NOT NULL;

CREATE TABLE legal_source_revisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  legal_source_id UUID NOT NULL REFERENCES legal_sources(id) ON DELETE RESTRICT,
  revision INT NOT NULL CHECK (revision > 0),
  source_version TEXT NOT NULL,
  content_hash TEXT,
  raw_text TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (legal_source_id, revision)
);

INSERT INTO legal_source_revisions (
  legal_source_id, revision, source_version, content_hash, raw_text, metadata,
  provenance, recorded_at
)
SELECT id, revision, source_version, content_hash, COALESCE(raw_text, ''), metadata,
  jsonb_strip_nulls(jsonb_build_object(
    'authority', authority,
    'canonical_source_name', canonical_source_name,
    'official_source_url', official_source_url,
    'external_id', external_id,
    'ingestion_method', ingestion_method,
    'fetched_at', fetched_at,
    'last_verified_at', last_verified_at
  )),
  fetched_at
FROM legal_sources;

CREATE TABLE source_sync_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_adapter TEXT NOT NULL,
  filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'partial', 'failed', 'captcha_required')),
  records_reported INT CHECK (records_reported IS NULL OR records_reported >= 0),
  processed_count INT NOT NULL DEFAULT 0 CHECK (processed_count >= 0),
  created_count INT NOT NULL DEFAULT 0 CHECK (created_count >= 0),
  updated_count INT NOT NULL DEFAULT 0 CHECK (updated_count >= 0),
  unchanged_count INT NOT NULL DEFAULT 0 CHECK (unchanged_count >= 0),
  duplicate_count INT NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
  failed_count INT NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
  error_message TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_source_sync_runs_adapter_time
  ON source_sync_runs (source_adapter, started_at DESC);

CREATE TABLE legal_source_quarantine (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_adapter TEXT NOT NULL,
  external_id TEXT,
  reason_code TEXT NOT NULL,
  reason TEXT NOT NULL,
  raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_hash TEXT,
  quarantined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolution_note TEXT
);
CREATE INDEX idx_legal_source_quarantine_pending
  ON legal_source_quarantine (source_adapter, quarantined_at DESC)
  WHERE resolved_at IS NULL;

ALTER TABLE legislation_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_source_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_sync_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_source_quarantine ENABLE ROW LEVEL SECURITY;

CREATE POLICY legislation_identities_read ON legislation_identities FOR SELECT USING (TRUE);
CREATE POLICY legal_source_revisions_read ON legal_source_revisions FOR SELECT USING (TRUE);
CREATE POLICY source_sync_runs_read ON source_sync_runs FOR SELECT USING (TRUE);
CREATE POLICY legal_source_quarantine_admin ON legal_source_quarantine FOR ALL
  USING (app_has_global_role('admin')) WITH CHECK (app_has_global_role('admin'));

GRANT SELECT ON legislation_identities, legal_source_revisions, source_sync_runs
  TO nhr_runtime;

COMMIT;
