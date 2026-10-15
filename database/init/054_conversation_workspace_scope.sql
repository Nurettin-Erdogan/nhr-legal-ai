BEGIN;
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS case_id UUID REFERENCES office_cases(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS office_project_id UUID REFERENCES office_projects(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS selected_document_ids UUID[] NOT NULL DEFAULT '{}';
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='conversations'::regclass AND conname='conversations_workspace_scope_check') THEN
    ALTER TABLE conversations ADD CONSTRAINT conversations_workspace_scope_check CHECK (
      num_nonnulls(project_id,case_id,office_project_id)<=1
      AND (project_id IS NULL OR cardinality(selected_document_ids)=0)
      AND cardinality(selected_document_ids)<=40
      AND array_position(selected_document_ids,NULL) IS NULL
    );
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_conversations_case ON conversations(created_by,case_id,updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_office_project ON conversations(created_by,office_project_id,updated_at DESC) WHERE deleted_at IS NULL;

-- Invoker RLS + owner eşleşmesi: FK denetiminin RLS atlaması üzerinden yabancı kayıt bağlanamaz.
-- Büro kapsamı sonradan değiştirilemez; bağlı kayıt silinirse sohbet FK ile birlikte silinir.
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
    SELECT count(*) INTO visible_count FROM office_case_documents
    WHERE id=ANY(NEW.selected_document_ids) AND owner_id=NEW.created_by AND deleted_at IS NULL
      AND (target_case IS NULL OR case_id=target_case);
    IF visible_count<>cardinality(NEW.selected_document_ids) THEN
      RAISE EXCEPTION 'Sohbet belge seçimine erişilemiyor.' USING ERRCODE='23503';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS conversations_workspace_scope_guard ON conversations;
CREATE TRIGGER conversations_workspace_scope_guard BEFORE INSERT OR UPDATE ON conversations
FOR EACH ROW EXECUTE FUNCTION protect_conversation_workspace_scope();
-- Mevcut conversation/message/citation RLS politikaları korunur. Büro kapsamı
-- project_id=NULL olarak yalnız created_by'ye görünür; üyeli ortak proje yetkisi genişletilmez.
COMMIT;
