-- Kullanıcı silme zincirinin (ON DELETE CASCADE) aktif/çöpteki UYAP evraklarını
-- sessizce yok etmesini önle. Kasıtlı veri tasfiyesi ayrı, nhr_app yönetici oturumunda
-- app.allow_user_data_purge=on ile açıkça işaretlenmelidir.
CREATE OR REPLACE FUNCTION office_reject_unintentional_user_document_purge()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM office_case_documents WHERE owner_id = OLD.id)
     AND NOT (session_user = 'nhr_app' AND current_setting('app.allow_user_data_purge', true) = 'on') THEN
    RAISE EXCEPTION 'Bu kullanıcının belgeleri var; açık yönetici tasfiyesi olmadan kullanıcı silinemez'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_office_protect_user_documents ON users;
CREATE TRIGGER trg_office_protect_user_documents
BEFORE DELETE ON users
FOR EACH ROW EXECUTE FUNCTION office_reject_unintentional_user_document_purge();
