\set ON_ERROR_STOP on

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM projects
    WHERE id = '20000000-0000-0000-0000-000000000001'
      AND created_by = '10000000-0000-0000-0000-000000000001'
  ) THEN
    RAISE EXCEPTION 'V1 project.user_id, projects.created_by alanına taşınmadı.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM project_members
    WHERE project_id = '20000000-0000-0000-0000-000000000001'
      AND user_id = '10000000-0000-0000-0000-000000000001'
      AND member_role = 'owner'
  ) THEN
    RAISE EXCEPTION 'V1 proje sahibi project_members tablosuna taşınmadı.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM documents
    WHERE id = '30000000-0000-0000-0000-000000000001'
      AND uploaded_by = '10000000-0000-0000-0000-000000000001'
  ) THEN
    RAISE EXCEPTION 'V1 documents.user_id, uploaded_by alanına taşınmadı.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM conversations
    WHERE id = '40000000-0000-0000-0000-000000000001'
      AND created_by = '10000000-0000-0000-0000-000000000001'
  ) THEN
    RAISE EXCEPTION 'V1 conversations.user_id, created_by alanına taşınmadı.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM legislation_details
    WHERE legal_source_id = '50000000-0000-0000-0000-000000000001'
      AND law_name = 'Türk Borçlar Kanunu'
      AND article_no = '1'
  ) THEN
    RAISE EXCEPTION 'V1 mevzuat metadata alanları legislation_details tablosuna taşınmadı.';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM court_decision_details
    WHERE legal_source_id = '50000000-0000-0000-0000-000000000002'
      AND court_name = 'Yargıtay'
      AND chamber = '9. Hukuk Dairesi'
      AND docket_no = '2024/100'
      AND decision_no = '2025/200'
  ) THEN
    RAISE EXCEPTION 'V1 içtihat metadata alanları court_decision_details tablosuna taşınmadı.';
  END IF;

  IF (
    SELECT count(*)
    FROM citations
    WHERE message_id = '41000000-0000-0000-0000-000000000001'
      AND num_nonnulls(document_chunk_id, legal_chunk_id) = 1
      AND citation_order IN (1, 2)
      AND source_title IS NOT NULL
  ) <> 2 THEN
    RAISE EXCEPTION 'V1 citation kayıtları V2 chunk hedefi/sıra modeline taşınmadı.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'citations'
      AND column_name = 'legal_source_id'
  ) THEN
    RAISE EXCEPTION 'Redundant citations.legal_source_id alanı kaldırılmadı.';
  END IF;

  IF (SELECT count(*) FROM roles) <> 4 THEN
    RAISE EXCEPTION 'Başlangıç rolleri beklenen şekilde oluşturulmadı.';
  END IF;

  IF (
    SELECT count(*)
    FROM pg_class
    WHERE relnamespace = 'public'::regnamespace
      AND relrowsecurity
      AND relname IN (
        'users',
        'roles',
        'user_roles',
        'clients',
        'projects',
        'project_members',
        'documents',
        'document_chunks',
        'conversations',
        'messages',
        'legal_sources',
        'legislation_details',
        'court_decision_details',
        'legal_chunks',
        'citations',
        'saved_legal_sources',
        'activity_logs'
      )
  ) <> 17 THEN
    RAISE EXCEPTION 'Beklenen tüm V2 tablolarında RLS etkin değil.';
  END IF;
END;
$$;

SELECT 'V1 -> V2 migration assertions passed' AS result;
