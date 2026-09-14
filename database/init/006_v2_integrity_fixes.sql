BEGIN;

DROP POLICY projects_insert_policy ON projects;
CREATE POLICY projects_insert_policy ON projects
  FOR INSERT
  WITH CHECK (
    (
      created_by = app_current_user_id()
      OR app_has_global_role('admin')
    )
    AND (
      client_id IS NULL
      OR app_can_access_client(client_id)
      OR app_has_global_role('admin')
    )
  );

CREATE OR REPLACE FUNCTION protect_project_security_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF app_current_user_id() IS NULL OR app_has_global_role('admin') THEN
    RETURN NEW;
  END IF;

  IF TG_OP = 'UPDATE'
    AND NEW.created_by IS DISTINCT FROM OLD.created_by
  THEN
    RAISE EXCEPTION 'projects.created_by değiştirilemez.';
  END IF;

  IF NEW.client_id IS NOT NULL
    AND (
      TG_OP = 'INSERT'
      OR NEW.client_id IS DISTINCT FROM OLD.client_id
    )
    AND NOT app_can_access_client(NEW.client_id)
  THEN
    RAISE EXCEPTION 'Erişilmeyen bir müvekkil projeye bağlanamaz.';
  END IF;

  IF TG_OP = 'UPDATE'
    AND (
      NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
      OR NEW.deleted_by IS DISTINCT FROM OLD.deleted_by
    )
    AND app_project_role(OLD.id) NOT IN ('admin', 'owner')
  THEN
    RAISE EXCEPTION 'Projeyi yalnızca owner veya admin silebilir ya da geri açabilir.';
  END IF;

  IF NEW.deleted_by IS NOT NULL
    AND NEW.deleted_by <> app_current_user_id()
  THEN
    RAISE EXCEPTION 'projects.deleted_by aktif kullanıcı olmalıdır.';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER projects_protect_security_fields ON projects;
CREATE TRIGGER projects_protect_security_fields
BEFORE INSERT OR UPDATE ON projects
FOR EACH ROW
EXECUTE FUNCTION protect_project_security_fields();

CREATE OR REPLACE FUNCTION check_legal_source_subtype(target_source_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  target_source_type TEXT;
  legislation_count INT;
  decision_count INT;
BEGIN
  SELECT source_type
  INTO target_source_type
  FROM legal_sources
  WHERE id = target_source_id;

  IF NOT FOUND THEN
    RETURN;
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
END;
$$;

CREATE OR REPLACE FUNCTION enforce_legal_source_subtype()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
  IF TG_TABLE_NAME = 'legal_sources' THEN
    IF TG_OP = 'DELETE' THEN
      PERFORM check_legal_source_subtype(OLD.id);
    ELSE
      PERFORM check_legal_source_subtype(NEW.id);
    END IF;

    RETURN NULL;
  END IF;

  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    PERFORM check_legal_source_subtype(OLD.legal_source_id);
  END IF;

  IF TG_OP IN ('INSERT', 'UPDATE')
    AND (
      TG_OP = 'INSERT'
      OR NEW.legal_source_id IS DISTINCT FROM OLD.legal_source_id
    )
  THEN
    PERFORM check_legal_source_subtype(NEW.legal_source_id);
  END IF;

  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_citation_assistant_message()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM 1
  FROM messages
  WHERE id = NEW.message_id
    AND role = 'assistant'
  FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Citation yalnızca assistant mesajına bağlanabilir.';
  END IF;

  RETURN NEW;
END;
$$;

COMMIT;
