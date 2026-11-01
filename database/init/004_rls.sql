BEGIN;

CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS UUID
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
  RETURN NULLIF(current_setting('app.user_id', TRUE), '')::UUID;
EXCEPTION
  WHEN invalid_text_representation THEN
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION app_has_global_role(required_role TEXT)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.user_roles AS assignment
    JOIN public.roles AS role ON role.id = assignment.role_id
    JOIN public.users AS app_user ON app_user.id = assignment.user_id
    WHERE assignment.user_id = public.app_current_user_id()
      AND role.code = required_role
      AND app_user.status = 'active'
      AND app_user.deleted_at IS NULL
  );
$$;

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

CREATE OR REPLACE FUNCTION app_can_access_project(target_project_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT public.app_project_role(target_project_id) IS NOT NULL;
$$;

CREATE OR REPLACE FUNCTION app_can_edit_project(target_project_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT public.app_project_role(target_project_id) IN ('admin', 'owner', 'editor');
$$;

CREATE OR REPLACE FUNCTION app_can_access_client(target_client_id UUID)
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
    )
    OR EXISTS (
      SELECT 1
      FROM public.projects AS project
      WHERE project.client_id = target_client_id
        AND project.deleted_at IS NULL
        AND public.app_can_access_project(project.id)
    );
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

CREATE OR REPLACE FUNCTION app_can_access_document(target_document_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.documents AS document
    WHERE document.id = target_document_id
      AND document.deleted_at IS NULL
      AND (
        (
          document.project_id IS NULL
          AND document.uploaded_by = public.app_current_user_id()
        )
        OR (
          document.project_id IS NOT NULL
          AND public.app_can_access_project(document.project_id)
        )
      )
  );
$$;

CREATE OR REPLACE FUNCTION app_can_edit_document(target_document_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.documents AS document
    WHERE document.id = target_document_id
      AND document.deleted_at IS NULL
      AND (
        (
          document.project_id IS NULL
          AND document.uploaded_by = public.app_current_user_id()
        )
        OR (
          document.project_id IS NOT NULL
          AND public.app_can_edit_project(document.project_id)
        )
      )
  );
$$;

CREATE OR REPLACE FUNCTION app_can_access_conversation(target_conversation_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.conversations AS conversation
    WHERE conversation.id = target_conversation_id
      AND conversation.deleted_at IS NULL
      AND (
        (
          conversation.project_id IS NULL
          AND conversation.created_by = public.app_current_user_id()
        )
        OR (
          conversation.project_id IS NOT NULL
          AND public.app_can_access_project(conversation.project_id)
        )
      )
  );
$$;

CREATE OR REPLACE FUNCTION app_can_edit_conversation(target_conversation_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.conversations AS conversation
    WHERE conversation.id = target_conversation_id
      AND conversation.deleted_at IS NULL
      AND (
        (
          conversation.project_id IS NULL
          AND conversation.created_by = public.app_current_user_id()
        )
        OR (
          conversation.project_id IS NOT NULL
          AND public.app_can_edit_project(conversation.project_id)
        )
      )
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

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE legislation_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE court_decision_details ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE citations ENABLE ROW LEVEL SECURITY;
ALTER TABLE saved_legal_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY users_select_policy ON users
  FOR SELECT
  USING (id = app_current_user_id() OR app_has_global_role('admin'));
CREATE POLICY users_update_policy ON users
  FOR UPDATE
  USING (id = app_current_user_id() OR app_has_global_role('admin'))
  WITH CHECK (id = app_current_user_id() OR app_has_global_role('admin'));

CREATE POLICY roles_select_policy ON roles
  FOR SELECT
  USING (TRUE);
CREATE POLICY roles_admin_write_policy ON roles
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY user_roles_select_policy ON user_roles
  FOR SELECT
  USING (user_id = app_current_user_id() OR app_has_global_role('admin'));
CREATE POLICY user_roles_admin_write_policy ON user_roles
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY clients_select_policy ON clients
  FOR SELECT
  USING (app_can_access_client(id));
CREATE POLICY clients_insert_policy ON clients
  FOR INSERT
  WITH CHECK (
    created_by = app_current_user_id()
    OR app_has_global_role('admin')
  );
CREATE POLICY clients_update_policy ON clients
  FOR UPDATE
  USING (app_can_edit_client(id))
  WITH CHECK (app_can_edit_client(id));
CREATE POLICY clients_delete_policy ON clients
  FOR DELETE
  USING (app_can_edit_client(id));

CREATE POLICY projects_select_policy ON projects
  FOR SELECT
  USING (app_can_access_project(id));
CREATE POLICY projects_insert_policy ON projects
  FOR INSERT
  WITH CHECK (
    created_by = app_current_user_id()
    OR app_has_global_role('admin')
  );
CREATE POLICY projects_update_policy ON projects
  FOR UPDATE
  USING (app_can_edit_project(id))
  WITH CHECK (app_can_edit_project(id));
CREATE POLICY projects_delete_policy ON projects
  FOR DELETE
  USING (app_project_role(id) IN ('admin', 'owner'));

CREATE POLICY project_members_select_policy ON project_members
  FOR SELECT
  USING (app_can_access_project(project_id));
CREATE POLICY project_members_insert_policy ON project_members
  FOR INSERT
  WITH CHECK (
    app_project_role(project_id) IN ('admin', 'owner')
    OR app_can_bootstrap_project_owner(project_id, user_id, member_role)
  );
CREATE POLICY project_members_update_policy ON project_members
  FOR UPDATE
  USING (app_project_role(project_id) IN ('admin', 'owner'))
  WITH CHECK (app_project_role(project_id) IN ('admin', 'owner'));
CREATE POLICY project_members_delete_policy ON project_members
  FOR DELETE
  USING (app_project_role(project_id) IN ('admin', 'owner'));

CREATE POLICY documents_select_policy ON documents
  FOR SELECT
  USING (app_can_access_document(id));
CREATE POLICY documents_insert_policy ON documents
  FOR INSERT
  WITH CHECK (
    uploaded_by = app_current_user_id()
    AND (
      project_id IS NULL
      OR app_can_edit_project(project_id)
    )
  );
CREATE POLICY documents_update_policy ON documents
  FOR UPDATE
  USING (app_can_edit_document(id))
  WITH CHECK (app_can_edit_document(id));
CREATE POLICY documents_delete_policy ON documents
  FOR DELETE
  USING (app_can_edit_document(id));

CREATE POLICY document_chunks_select_policy ON document_chunks
  FOR SELECT
  USING (app_can_access_document(document_id));
CREATE POLICY document_chunks_insert_policy ON document_chunks
  FOR INSERT
  WITH CHECK (app_can_edit_document(document_id));
CREATE POLICY document_chunks_update_policy ON document_chunks
  FOR UPDATE
  USING (app_can_edit_document(document_id))
  WITH CHECK (app_can_edit_document(document_id));
CREATE POLICY document_chunks_delete_policy ON document_chunks
  FOR DELETE
  USING (app_can_edit_document(document_id));

CREATE POLICY conversations_select_policy ON conversations
  FOR SELECT
  USING (app_can_access_conversation(id));
CREATE POLICY conversations_insert_policy ON conversations
  FOR INSERT
  WITH CHECK (
    created_by = app_current_user_id()
    AND (
      project_id IS NULL
      OR app_can_access_project(project_id)
    )
  );
CREATE POLICY conversations_update_policy ON conversations
  FOR UPDATE
  USING (app_can_edit_conversation(id))
  WITH CHECK (app_can_edit_conversation(id));
CREATE POLICY conversations_delete_policy ON conversations
  FOR DELETE
  USING (app_can_edit_conversation(id));

CREATE POLICY messages_select_policy ON messages
  FOR SELECT
  USING (app_can_access_conversation(conversation_id));
CREATE POLICY messages_insert_policy ON messages
  FOR INSERT
  WITH CHECK (app_can_edit_conversation(conversation_id));
CREATE POLICY messages_update_policy ON messages
  FOR UPDATE
  USING (app_can_edit_conversation(conversation_id))
  WITH CHECK (app_can_edit_conversation(conversation_id));
CREATE POLICY messages_delete_policy ON messages
  FOR DELETE
  USING (app_can_edit_conversation(conversation_id));

CREATE POLICY legal_sources_select_policy ON legal_sources
  FOR SELECT
  USING (deleted_at IS NULL OR app_has_global_role('admin'));
CREATE POLICY legal_sources_admin_write_policy ON legal_sources
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY legislation_details_select_policy ON legislation_details
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM legal_sources AS source
      WHERE source.id = legal_source_id
        AND (source.deleted_at IS NULL OR app_has_global_role('admin'))
    )
  );
CREATE POLICY legislation_details_admin_write_policy ON legislation_details
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY court_decision_details_select_policy ON court_decision_details
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM legal_sources AS source
      WHERE source.id = legal_source_id
        AND (source.deleted_at IS NULL OR app_has_global_role('admin'))
    )
  );
CREATE POLICY court_decision_details_admin_write_policy ON court_decision_details
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY legal_chunks_select_policy ON legal_chunks
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM legal_sources AS source
      WHERE source.id = legal_source_id
        AND (source.deleted_at IS NULL OR app_has_global_role('admin'))
    )
  );
CREATE POLICY legal_chunks_admin_write_policy ON legal_chunks
  FOR ALL
  USING (app_has_global_role('admin'))
  WITH CHECK (app_has_global_role('admin'));

CREATE POLICY citations_select_policy ON citations
  FOR SELECT
  USING (
    EXISTS (
      SELECT 1
      FROM messages AS message
      WHERE message.id = message_id
        AND app_can_access_conversation(message.conversation_id)
    )
  );
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
CREATE POLICY citations_delete_policy ON citations
  FOR DELETE
  USING (
    EXISTS (
      SELECT 1
      FROM messages AS message
      WHERE message.id = message_id
        AND app_can_edit_conversation(message.conversation_id)
    )
  );

CREATE POLICY saved_legal_sources_owner_policy ON saved_legal_sources
  FOR ALL
  USING (user_id = app_current_user_id())
  WITH CHECK (user_id = app_current_user_id());

CREATE POLICY activity_logs_select_policy ON activity_logs
  FOR SELECT
  USING (
    actor_user_id = app_current_user_id()
    OR app_has_global_role('admin')
  );
CREATE POLICY activity_logs_insert_policy ON activity_logs
  FOR INSERT
  WITH CHECK (actor_user_id = app_current_user_id());

COMMIT;
