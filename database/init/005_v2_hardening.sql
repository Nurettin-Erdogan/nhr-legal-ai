BEGIN;

CREATE OR REPLACE FUNCTION app_project_role(target_project_id UUID)
RETURNS TEXT
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT CASE
    WHEN public.app_has_global_role('admin') THEN 'admin'
    ELSE (
      SELECT member.member_role
      FROM public.project_members AS member
      JOIN public.projects AS project ON project.id = member.project_id
      JOIN public.users AS app_user ON app_user.id = member.user_id
      WHERE member.project_id = target_project_id
        AND member.user_id = public.app_current_user_id()
        AND project.deleted_at IS NULL
        AND app_user.status = 'active'
        AND app_user.deleted_at IS NULL
    )
  END;
$$;

CREATE OR REPLACE FUNCTION app_can_edit_client(target_client_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT public.app_has_global_role('admin')
    OR EXISTS (
      SELECT 1
      FROM public.clients AS client
      WHERE client.id = target_client_id
        AND client.deleted_at IS NULL
        AND client.created_by = public.app_current_user_id()
    );
$$;

CREATE OR REPLACE FUNCTION app_can_bootstrap_project_owner(
  target_project_id UUID,
  target_user_id UUID,
  target_member_role TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT target_user_id = public.app_current_user_id()
    AND target_member_role = 'owner'
    AND EXISTS (
      SELECT 1
      FROM public.projects AS project
      WHERE project.id = target_project_id
        AND project.created_by = public.app_current_user_id()
        AND project.deleted_at IS NULL
        AND NOT EXISTS (
          SELECT 1
          FROM public.project_members AS existing_member
          WHERE existing_member.project_id = target_project_id
        )
    );
$$;

CREATE OR REPLACE FUNCTION app_can_use_citation_target(
  target_document_chunk_id UUID,
  target_legal_chunk_id UUID
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT CASE
    WHEN target_document_chunk_id IS NOT NULL
      AND target_legal_chunk_id IS NULL
    THEN EXISTS (
      SELECT 1
      FROM public.document_chunks AS chunk
      WHERE chunk.id = target_document_chunk_id
        AND public.app_can_access_document(chunk.document_id)
    )
    WHEN target_document_chunk_id IS NULL
      AND target_legal_chunk_id IS NOT NULL
    THEN EXISTS (
      SELECT 1
      FROM public.legal_chunks AS chunk
      JOIN public.legal_sources AS source
        ON source.id = chunk.legal_source_id
      WHERE chunk.id = target_legal_chunk_id
        AND source.deleted_at IS NULL
    )
    ELSE FALSE
  END;
$$;

DROP POLICY project_members_insert_policy ON project_members;
CREATE POLICY project_members_insert_policy ON project_members
  FOR INSERT
  WITH CHECK (
    app_project_role(project_id) IN ('admin', 'owner')
    OR app_can_bootstrap_project_owner(project_id, user_id, member_role)
  );

DROP POLICY citations_insert_policy ON citations;
CREATE POLICY citations_insert_policy ON citations
  FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM messages AS message
      WHERE message.id = message_id
        AND app_can_edit_conversation(message.conversation_id)
    )
    AND app_can_use_citation_target(document_chunk_id, legal_chunk_id)
  );

DROP POLICY citations_update_policy ON citations;
CREATE POLICY citations_update_policy ON citations
  FOR UPDATE
  USING (
    EXISTS (
      SELECT 1
      FROM messages AS message
      WHERE message.id = message_id
        AND app_can_edit_conversation(message.conversation_id)
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM messages AS message
      WHERE message.id = message_id
        AND app_can_edit_conversation(message.conversation_id)
    )
    AND app_can_use_citation_target(document_chunk_id, legal_chunk_id)
  );

CREATE OR REPLACE FUNCTION protect_user_security_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF app_current_user_id() IS NOT NULL
    AND NOT app_has_global_role('admin')
    AND (
      NEW.email IS DISTINCT FROM OLD.email
      OR NEW.status IS DISTINCT FROM OLD.status
      OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
      OR NEW.deleted_by IS DISTINCT FROM OLD.deleted_by
    )
  THEN
    RAISE EXCEPTION
      'email, status ve kullanıcı silme alanları yalnızca admin tarafından değiştirilebilir.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER users_protect_security_fields
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION protect_user_security_fields();

CREATE OR REPLACE FUNCTION protect_project_security_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF app_current_user_id() IS NULL OR app_has_global_role('admin') THEN
    RETURN NEW;
  END IF;

  IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
    RAISE EXCEPTION 'projects.created_by değiştirilemez.';
  END IF;

  IF NEW.client_id IS DISTINCT FROM OLD.client_id
    AND NEW.client_id IS NOT NULL
    AND NOT app_can_access_client(NEW.client_id)
  THEN
    RAISE EXCEPTION 'Erişilmeyen bir müvekkil projeye bağlanamaz.';
  END IF;

  IF NEW.deleted_by IS NOT NULL
    AND NEW.deleted_by <> app_current_user_id()
  THEN
    RAISE EXCEPTION 'projects.deleted_by aktif kullanıcı olmalıdır.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER projects_protect_security_fields
BEFORE UPDATE ON projects
FOR EACH ROW
EXECUTE FUNCTION protect_project_security_fields();

CREATE OR REPLACE FUNCTION protect_document_security_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF app_current_user_id() IS NULL OR app_has_global_role('admin') THEN
    RETURN NEW;
  END IF;

  IF NEW.uploaded_by IS DISTINCT FROM OLD.uploaded_by THEN
    RAISE EXCEPTION 'documents.uploaded_by değiştirilemez.';
  END IF;

  IF NEW.project_id IS DISTINCT FROM OLD.project_id THEN
    IF NEW.project_id IS NOT NULL
      AND NOT app_can_edit_project(NEW.project_id)
    THEN
      RAISE EXCEPTION 'Belge, düzenleme yetkisi olmayan projeye taşınamaz.';
    END IF;

    IF NEW.project_id IS NULL
      AND NEW.uploaded_by <> app_current_user_id()
    THEN
      RAISE EXCEPTION 'Belge yalnız yükleyen kullanıcıya ait kişisel alana taşınabilir.';
    END IF;
  END IF;

  IF NEW.deleted_by IS NOT NULL
    AND NEW.deleted_by <> app_current_user_id()
  THEN
    RAISE EXCEPTION 'documents.deleted_by aktif kullanıcı olmalıdır.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER documents_protect_security_fields
BEFORE UPDATE ON documents
FOR EACH ROW
EXECUTE FUNCTION protect_document_security_fields();

CREATE OR REPLACE FUNCTION protect_conversation_security_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF app_current_user_id() IS NULL OR app_has_global_role('admin') THEN
    RETURN NEW;
  END IF;

  IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
    RAISE EXCEPTION 'conversations.created_by değiştirilemez.';
  END IF;

  IF NEW.project_id IS DISTINCT FROM OLD.project_id THEN
    IF NEW.project_id IS NOT NULL
      AND NOT app_can_edit_project(NEW.project_id)
    THEN
      RAISE EXCEPTION 'Konuşma, düzenleme yetkisi olmayan projeye taşınamaz.';
    END IF;

    IF NEW.project_id IS NULL
      AND NEW.created_by <> app_current_user_id()
    THEN
      RAISE EXCEPTION 'Konuşma yalnız oluşturan kullanıcının kişisel alanına taşınabilir.';
    END IF;
  END IF;

  IF NEW.deleted_by IS NOT NULL
    AND NEW.deleted_by <> app_current_user_id()
  THEN
    RAISE EXCEPTION 'conversations.deleted_by aktif kullanıcı olmalıdır.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER conversations_protect_security_fields
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION protect_conversation_security_fields();

CREATE OR REPLACE FUNCTION protect_cited_message_role()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.role <> 'assistant'
    AND EXISTS (
      SELECT 1
      FROM citations
      WHERE message_id = OLD.id
    )
  THEN
    RAISE EXCEPTION 'Citation bulunan mesajın rolü assistant dışına değiştirilemez.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER messages_protect_cited_role
BEFORE UPDATE OF role ON messages
FOR EACH ROW
EXECUTE FUNCTION protect_cited_message_role();

CREATE OR REPLACE FUNCTION enforce_project_owner()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  target_project_id UUID;
BEGIN
  IF TG_TABLE_NAME = 'projects' THEN
    target_project_id := NEW.id;

    IF NOT EXISTS (
      SELECT 1
      FROM projects
      WHERE id = target_project_id
    ) THEN
      RETURN NULL;
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM project_members
      WHERE project_id = target_project_id
        AND member_role = 'owner'
    ) THEN
      RAISE EXCEPTION 'Her proje transaction sonunda bir owner üyeye sahip olmalıdır.';
    END IF;

    RETURN NULL;
  END IF;

  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    target_project_id := OLD.project_id;

    IF EXISTS (SELECT 1 FROM projects WHERE id = target_project_id)
      AND NOT EXISTS (
        SELECT 1
        FROM project_members
        WHERE project_id = target_project_id
          AND member_role = 'owner'
      )
    THEN
      RAISE EXCEPTION 'Projenin son owner üyesi kaldırılamaz.';
    END IF;
  END IF;

  IF TG_OP IN ('INSERT', 'UPDATE') THEN
    target_project_id := NEW.project_id;

    IF EXISTS (SELECT 1 FROM projects WHERE id = target_project_id)
      AND NOT EXISTS (
        SELECT 1
        FROM project_members
        WHERE project_id = target_project_id
          AND member_role = 'owner'
      )
    THEN
      RAISE EXCEPTION 'Her proje transaction sonunda bir owner üyeye sahip olmalıdır.';
    END IF;
  END IF;

  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER projects_require_owner
AFTER INSERT ON projects
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_project_owner();

CREATE CONSTRAINT TRIGGER project_members_require_owner
AFTER INSERT OR UPDATE OR DELETE ON project_members
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_project_owner();

CREATE OR REPLACE FUNCTION enforce_legal_source_subtype()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  target_source_id UUID;
  target_source_type TEXT;
  legislation_count INT;
  decision_count INT;
BEGIN
  IF TG_TABLE_NAME = 'legal_sources' THEN
    target_source_id := COALESCE(NEW.id, OLD.id);
  ELSE
    target_source_id := COALESCE(NEW.legal_source_id, OLD.legal_source_id);
  END IF;

  SELECT source_type
  INTO target_source_type
  FROM legal_sources
  WHERE id = target_source_id;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  SELECT count(*)
  INTO legislation_count
  FROM legislation_details
  WHERE legal_source_id = target_source_id;

  SELECT count(*)
  INTO decision_count
  FROM court_decision_details
  WHERE legal_source_id = target_source_id;

  IF target_source_type = 'legislation'
    AND (legislation_count <> 1 OR decision_count <> 0)
  THEN
    RAISE EXCEPTION 'legislation kaynağı tam bir legislation_details kaydı taşımalıdır.';
  ELSIF target_source_type = 'court_decision'
    AND (decision_count <> 1 OR legislation_count <> 0)
  THEN
    RAISE EXCEPTION 'court_decision kaynağı tam bir court_decision_details kaydı taşımalıdır.';
  ELSIF target_source_type = 'other'
    AND (legislation_count <> 0 OR decision_count <> 0)
  THEN
    RAISE EXCEPTION 'other kaynağı tiplenmiş hukuk detayı taşıyamaz.';
  END IF;

  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER legal_sources_require_subtype
AFTER INSERT OR UPDATE OF source_type ON legal_sources
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_legal_source_subtype();

CREATE CONSTRAINT TRIGGER legislation_details_match_source
AFTER INSERT OR UPDATE OR DELETE ON legislation_details
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_legal_source_subtype();

CREATE CONSTRAINT TRIGGER court_decision_details_match_source
AFTER INSERT OR UPDATE OR DELETE ON court_decision_details
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION enforce_legal_source_subtype();

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'nhr_runtime'
  ) THEN
    CREATE ROLE nhr_runtime
      NOLOGIN
      NOSUPERUSER
      NOCREATEDB
      NOCREATEROLE
      NOINHERIT
      NOBYPASSRLS;
  END IF;
END;
$$;

DO $$
BEGIN
  EXECUTE format(
    'GRANT CONNECT ON DATABASE %I TO nhr_runtime',
    current_database()
  );
END;
$$;

GRANT USAGE ON SCHEMA public TO nhr_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nhr_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nhr_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO nhr_runtime;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nhr_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO nhr_runtime;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO nhr_runtime;

COMMIT;
