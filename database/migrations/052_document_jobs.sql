\set ON_ERROR_STOP on
BEGIN;
CREATE TABLE IF NOT EXISTS office_document_jobs (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  module TEXT NOT NULL CHECK (module IN ('document_analysis','auto_summary','risk_analysis','draft')),
  state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued','running','done','partial','failed','cancelled')),
  document_ids UUID[] NOT NULL DEFAULT '{}',
  payload JSONB NOT NULL,
  progress JSONB NOT NULL DEFAULT '{}',
  output_id UUID REFERENCES office_ai_outputs(id) ON DELETE SET NULL,
  lease UUID,
  leased_until TIMESTAMPTZ,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (cardinality(document_ids) <= 2000)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_document_jobs_one_active ON office_document_jobs(owner_id) WHERE state IN ('queued','running');
CREATE INDEX IF NOT EXISTS idx_document_jobs_owner ON office_document_jobs(owner_id, created_at DESC);
ALTER TABLE office_document_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_document_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_jobs_owner ON office_document_jobs;
CREATE POLICY document_jobs_owner ON office_document_jobs FOR ALL
  USING (owner_id=app_current_user_id()) WITH CHECK (owner_id=app_current_user_id());
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nhr_runtime') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON office_document_jobs TO nhr_runtime;
  END IF;
END $$;
-- Kaynak kalıcı silinirse kuyruğun türetilmiş metni ve ilgili AI çıktısı da temizlenir.
CREATE OR REPLACE FUNCTION remove_document_job_derivatives() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Önce işi kilitle: eşzamanlı son kayıt, kaynak silinirken yetim çıktı bırakamaz.
  PERFORM id FROM office_document_jobs WHERE owner_id=OLD.owner_id AND OLD.id=ANY(document_ids) FOR UPDATE;
  DELETE FROM office_ai_outputs WHERE owner_id=OLD.owner_id AND id IN
    (SELECT output_id FROM office_document_jobs WHERE owner_id=OLD.owner_id AND OLD.id=ANY(document_ids));
  DELETE FROM office_document_jobs WHERE owner_id=OLD.owner_id AND OLD.id=ANY(document_ids);
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS office_document_job_purge ON office_case_documents;
CREATE TRIGGER office_document_job_purge BEFORE DELETE ON office_case_documents
  FOR EACH ROW EXECUTE FUNCTION remove_document_job_derivatives();
CREATE OR REPLACE FUNCTION remove_document_output_job() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM office_document_jobs WHERE owner_id=OLD.owner_id AND output_id=OLD.id;
  RETURN OLD;
END $$;
DROP TRIGGER IF EXISTS office_document_output_job_purge ON office_ai_outputs;
CREATE TRIGGER office_document_output_job_purge BEFORE DELETE ON office_ai_outputs
  FOR EACH ROW EXECUTE FUNCTION remove_document_output_job();
COMMIT;
