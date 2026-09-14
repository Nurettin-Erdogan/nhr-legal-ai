\set ON_ERROR_STOP on

BEGIN;

INSERT INTO users (id, email, password_hash, full_name)
VALUES
  ('80000000-0000-0000-0000-000000000001', 'security-owner@example.test', 'test-hash', 'Security Owner'),
  ('80000000-0000-0000-0000-000000000002', 'security-editor@example.test', 'test-hash', 'Security Editor'),
  ('80000000-0000-0000-0000-000000000003', 'security-outsider@example.test', 'test-hash', 'Security Outsider');

INSERT INTO clients (id, display_name, created_by)
VALUES
  (
    '81000000-0000-0000-0000-000000000001',
    'Owner Müvekkili',
    '80000000-0000-0000-0000-000000000001'
  ),
  (
    '81000000-0000-0000-0000-000000000002',
    'Outsider Müvekkili',
    '80000000-0000-0000-0000-000000000003'
  );

INSERT INTO projects (id, client_id, created_by, name)
VALUES
  (
    '82000000-0000-0000-0000-000000000001',
    '81000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000001',
    'Owner Projesi'
  ),
  (
    '82000000-0000-0000-0000-000000000002',
    '81000000-0000-0000-0000-000000000002',
    '80000000-0000-0000-0000-000000000003',
    'Outsider Projesi'
  );

INSERT INTO project_members (project_id, user_id, member_role, added_by)
VALUES
  (
    '82000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000001',
    'owner',
    '80000000-0000-0000-0000-000000000001'
  ),
  (
    '82000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000002',
    'editor',
    '80000000-0000-0000-0000-000000000001'
  ),
  (
    '82000000-0000-0000-0000-000000000002',
    '80000000-0000-0000-0000-000000000003',
    'owner',
    '80000000-0000-0000-0000-000000000003'
  );

INSERT INTO documents (id, project_id, uploaded_by, file_name, status)
VALUES
  (
    '83000000-0000-0000-0000-000000000001',
    '82000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000001',
    'owner.pdf',
    'ready'
  ),
  (
    '83000000-0000-0000-0000-000000000002',
    '82000000-0000-0000-0000-000000000002',
    '80000000-0000-0000-0000-000000000003',
    'outsider.pdf',
    'ready'
  );

INSERT INTO document_chunks (id, document_id, chunk_index, content)
VALUES
  (
    '83100000-0000-0000-0000-000000000001',
    '83000000-0000-0000-0000-000000000001',
    0,
    'Owner projesindeki belge.'
  ),
  (
    '83100000-0000-0000-0000-000000000002',
    '83000000-0000-0000-0000-000000000002',
    0,
    'Outsider projesindeki gizli belge.'
  );

INSERT INTO conversations (id, project_id, created_by, title)
VALUES (
  '84000000-0000-0000-0000-000000000001',
  '82000000-0000-0000-0000-000000000001',
  '80000000-0000-0000-0000-000000000001',
  'Güvenlik testi'
);

INSERT INTO messages (id, conversation_id, role, content)
VALUES (
  '84100000-0000-0000-0000-000000000001',
  '84000000-0000-0000-0000-000000000001',
  'assistant',
  'Kaynaklı cevap'
);

INSERT INTO legal_sources (
  id,
  source_type,
  title,
  raw_text,
  ingest_status
)
VALUES (
  '85000000-0000-0000-0000-000000000001',
  'legislation',
  'Güvenlik Test Kanunu',
  'Test metni',
  'ready'
);

INSERT INTO legislation_details (
  legal_source_id,
  law_name,
  article_no
)
VALUES (
  '85000000-0000-0000-0000-000000000001',
  'Güvenlik Test Kanunu',
  '1'
);

INSERT INTO legal_chunks (id, legal_source_id, chunk_index, content)
VALUES (
  '85100000-0000-0000-0000-000000000001',
  '85000000-0000-0000-0000-000000000001',
  0,
  'Güvenlik Test Kanunu Madde 1.'
);

INSERT INTO citations (
  id,
  message_id,
  legal_chunk_id,
  citation_order,
  source_title
)
VALUES (
  '86000000-0000-0000-0000-000000000001',
  '84100000-0000-0000-0000-000000000001',
  '85100000-0000-0000-0000-000000000001',
  1,
  'Güvenlik Test Kanunu'
);

SET LOCAL ROLE nhr_runtime;
SET LOCAL app.user_id = '80000000-0000-0000-0000-000000000001';

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    INSERT INTO projects (id, client_id, created_by, name)
    VALUES (
      '82000000-0000-0000-0000-000000000004',
      '81000000-0000-0000-0000-000000000002',
      '80000000-0000-0000-0000-000000000001',
      'Yetkisiz müvekkil projesi'
    );
  EXCEPTION
    WHEN insufficient_privilege OR raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Kullanıcı erişemediği müvekkille proje oluşturabildi.';
  END IF;
END;
$$;

INSERT INTO projects (id, created_by, name)
VALUES (
  '82000000-0000-0000-0000-000000000003',
  '80000000-0000-0000-0000-000000000001',
  'RLS Bootstrap Projesi'
);

INSERT INTO project_members (project_id, user_id, member_role)
VALUES (
  '82000000-0000-0000-0000-000000000003',
  '80000000-0000-0000-0000-000000000001',
  'owner'
);

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    UPDATE users
    SET status = 'suspended'
    WHERE id = '80000000-0000-0000-0000-000000000001';
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Kullanıcı kendi status alanını değiştirebildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    UPDATE projects
    SET
      deleted_at = NOW(),
      deleted_by = '80000000-0000-0000-0000-000000000002'
    WHERE id = '82000000-0000-0000-0000-000000000001';
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Editör projeyi soft-delete edebildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    UPDATE messages
    SET role = 'user'
    WHERE id = '84100000-0000-0000-0000-000000000001';
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Citation bulunan mesajın rolü değiştirilebildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    DELETE FROM project_members
    WHERE project_id = '82000000-0000-0000-0000-000000000003'
      AND user_id = '80000000-0000-0000-0000-000000000001';
    SET CONSTRAINTS project_members_require_owner IMMEDIATE;
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  SET CONSTRAINTS project_members_require_owner DEFERRED;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Projenin son owner üyesi kaldırılabildi.';
  END IF;
END;
$$;

SET LOCAL app.user_id = '80000000-0000-0000-0000-000000000002';

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    UPDATE projects
    SET client_id = '81000000-0000-0000-0000-000000000002'
    WHERE id = '82000000-0000-0000-0000-000000000001';
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Editör erişemediği müvekkili projeye bağlayabildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    UPDATE projects
    SET created_by = '80000000-0000-0000-0000-000000000002'
    WHERE id = '82000000-0000-0000-0000-000000000001';
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Editör projects.created_by alanını değiştirebildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    INSERT INTO citations (
      message_id,
      document_chunk_id,
      citation_order,
      source_title
    )
    VALUES (
      '84100000-0000-0000-0000-000000000001',
      '83100000-0000-0000-0000-000000000002',
      2,
      'Yetkisiz belge'
    );
  EXCEPTION
    WHEN insufficient_privilege THEN
      rejected := TRUE;
  END;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Editör başka projedeki chunk için citation oluşturabildi.';
  END IF;
END;
$$;

RESET ROLE;
SET LOCAL app.user_id = '';

UPDATE users
SET status = 'suspended'
WHERE id = '80000000-0000-0000-0000-000000000002';

SET LOCAL ROLE nhr_runtime;
SET LOCAL app.user_id = '80000000-0000-0000-0000-000000000002';

DO $$
BEGIN
  IF (SELECT count(*) FROM projects) <> 0 THEN
    RAISE EXCEPTION 'Askıya alınmış kullanıcı proje erişimini korudu.';
  END IF;
END;
$$;

RESET ROLE;
SET LOCAL app.user_id = '';

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    INSERT INTO legal_sources (
      id,
      source_type,
      title,
      raw_text,
      ingest_status
    )
    VALUES (
      '85000000-0000-0000-0000-000000000002',
      'court_decision',
      'Detaysız karar',
      'Test',
      'ready'
    );
    SET CONSTRAINTS legal_sources_require_subtype IMMEDIATE;
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  SET CONSTRAINTS legal_sources_require_subtype DEFERRED;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Mahkeme kararı detay kaydı olmadan kabul edildi.';
  END IF;
END;
$$;

DO $$
DECLARE
  rejected BOOLEAN := FALSE;
BEGIN
  BEGIN
    INSERT INTO legal_sources (
      id,
      source_type,
      title,
      raw_text,
      ingest_status
    )
    VALUES (
      '85000000-0000-0000-0000-000000000003',
      'legislation',
      'İkinci mevzuat kaynağı',
      'Test',
      'ready'
    );

    UPDATE legislation_details
    SET legal_source_id = '85000000-0000-0000-0000-000000000003'
    WHERE legal_source_id = '85000000-0000-0000-0000-000000000001';

    SET CONSTRAINTS legislation_details_match_source IMMEDIATE;
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;

  SET CONSTRAINTS legislation_details_match_source DEFERRED;

  IF NOT rejected THEN
    RAISE EXCEPTION 'Subtype detayı taşınırken eski kaynak detaysız bırakılabildi.';
  END IF;
END;
$$;

ROLLBACK;
