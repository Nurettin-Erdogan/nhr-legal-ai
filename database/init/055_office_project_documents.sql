BEGIN;
CREATE TABLE IF NOT EXISTS office_project_documents (
  id UUID PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES office_projects(id) ON DELETE CASCADE,
  document_id UUID NOT NULL REFERENCES office_case_documents(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE(project_id,document_id)
);
CREATE INDEX IF NOT EXISTS idx_project_documents_owner ON office_project_documents(owner_id,project_id);
CREATE INDEX IF NOT EXISTS idx_project_documents_document ON office_project_documents(document_id);
ALTER TABLE office_project_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE office_project_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS project_documents_owner ON office_project_documents;
CREATE POLICY project_documents_owner ON office_project_documents FOR ALL
  USING (owner_id=app_current_user_id()) WITH CHECK (owner_id=app_current_user_id());
CREATE OR REPLACE FUNCTION protect_project_document_link() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP='UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
    OR NEW.project_id IS DISTINCT FROM OLD.project_id OR NEW.document_id IS DISTINCT FROM OLD.document_id) THEN
    RAISE EXCEPTION 'Belge bağlantısının kimliği değiştirilemez.' USING ERRCODE='23514';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM office_projects WHERE id=NEW.project_id AND owner_id=NEW.owner_id)
    OR NOT EXISTS (SELECT 1 FROM office_case_documents WHERE id=NEW.document_id AND owner_id=NEW.owner_id AND deleted_at IS NULL) THEN
    RAISE EXCEPTION 'Proje veya belgeye erişilemiyor.' USING ERRCODE='23503';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS project_document_link_guard ON office_project_documents;
CREATE TRIGGER project_document_link_guard BEFORE INSERT OR UPDATE ON office_project_documents
FOR EACH ROW EXECUTE FUNCTION protect_project_document_link();
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='nhr_runtime') THEN
    GRANT SELECT,INSERT,DELETE ON office_project_documents TO nhr_runtime;
  END IF;
END $$;

-- Proje kapsamı: bağlı davanın evrakları ile doğrudan bağlananların birleşimi.
-- Açık belge seçimli proje sohbeti başka bir kullanıcı belgesiyle genişletilemez.
CREATE OR REPLACE FUNCTION protect_conversation_workspace_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_case UUID; visible_count INTEGER;
BEGIN
  IF TG_OP='UPDATE' THEN
    IF NEW.case_id IS DISTINCT FROM OLD.case_id
       OR NEW.office_project_id IS DISTINCT FROM OLD.office_project_id
       OR NEW.selected_document_ids IS DISTINCT FROM OLD.selected_document_ids THEN
      RAISE EXCEPTION 'Sohbetin belge/dava/proje kapsamı değiştirilemez.' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  target_case := NEW.case_id;
  IF NEW.case_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM office_cases WHERE id=NEW.case_id AND owner_id=NEW.created_by
  ) THEN
    RAISE EXCEPTION 'Sohbet kapsamına erişilemiyor.' USING ERRCODE='23503';
  END IF;
  IF NEW.office_project_id IS NOT NULL THEN
    SELECT case_id INTO target_case FROM office_projects WHERE id=NEW.office_project_id AND owner_id=NEW.created_by;
    IF NOT FOUND OR (target_case IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM office_cases WHERE id=target_case AND owner_id=NEW.created_by
    )) THEN
      RAISE EXCEPTION 'Sohbet kapsamına erişilemiyor.' USING ERRCODE='23503';
    END IF;
  END IF;
  IF cardinality(NEW.selected_document_ids)>0 THEN
    SELECT count(*) INTO visible_count FROM office_case_documents od
    WHERE od.id=ANY(NEW.selected_document_ids) AND od.owner_id=NEW.created_by AND od.deleted_at IS NULL
      AND (
        (NEW.office_project_id IS NULL AND (target_case IS NULL OR od.case_id=target_case))
        OR (NEW.office_project_id IS NOT NULL AND (od.case_id=target_case OR EXISTS (
          SELECT 1 FROM office_project_documents link WHERE link.project_id=NEW.office_project_id AND link.document_id=od.id
        )))
      );
    IF visible_count<>cardinality(NEW.selected_document_ids) THEN
      RAISE EXCEPTION 'Sohbet belge seçimine erişilemiyor.' USING ERRCODE='23503';
    END IF;
  END IF;
  RETURN NEW;
END $$;
COMMIT;
