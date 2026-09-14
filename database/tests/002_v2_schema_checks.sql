\set ON_ERROR_STOP on

BEGIN;

INSERT INTO users (id, email, password_hash, full_name)
VALUES
  ('70000000-0000-0000-0000-000000000001', 'v2-owner@example.test', 'test-hash', 'V2 Owner'),
  ('70000000-0000-0000-0000-000000000002', 'v2-editor@example.test', 'test-hash', 'V2 Editor'),
  ('70000000-0000-0000-0000-000000000003', 'v2-outsider@example.test', 'test-hash', 'V2 Outsider');

INSERT INTO user_roles (user_id, role_id)
SELECT
  '70000000-0000-0000-0000-000000000001',
  id
FROM roles
WHERE code = 'lawyer';

INSERT INTO clients (
  id,
  client_type,
  display_name,
  identity_number_last4,
  created_by
)
VALUES (
  '71000000-0000-0000-0000-000000000001',
  'individual',
  'Test Müvekkil',
  '1234',
  '70000000-0000-0000-0000-000000000001'
);

INSERT INTO projects (
  id,
  client_id,
  created_by,
  name,
  matter_type,
  status,
  docket_no
)
VALUES (
  '72000000-0000-0000-0000-000000000001',
  '71000000-0000-0000-0000-000000000001',
  '70000000-0000-0000-0000-000000000001',
  'V2 Davası',
  'case',
  'active',
  '2026/100'
);

INSERT INTO project_members (project_id, user_id, member_role, added_by)
VALUES
  (
    '72000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    'owner',
    '70000000-0000-0000-0000-000000000001'
  ),
  (
    '72000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000002',
    'editor',
    '70000000-0000-0000-0000-000000000001'
  );

INSERT INTO documents (
  id,
  project_id,
  uploaded_by,
  file_name,
  mime_type,
  storage_key,
  status,
  file_size,
  checksum_sha256
)
VALUES (
  '73000000-0000-0000-0000-000000000001',
  '72000000-0000-0000-0000-000000000001',
  '70000000-0000-0000-0000-000000000001',
  'test-belgesi.pdf',
  'application/pdf',
  'tests/test-belgesi.pdf',
  'ready',
  100,
  repeat('a', 64)
);

INSERT INTO document_chunks (
  id,
  document_id,
  chunk_index,
  content,
  page_number,
  token_count
)
VALUES (
  '73100000-0000-0000-0000-000000000001',
  '73000000-0000-0000-0000-000000000001',
  0,
  'Test belgesinin kaynak olarak kullanılacak metni.',
  1,
  8
);

INSERT INTO legal_sources (
  id,
  source_type,
  title,
  external_id,
  authority,
  raw_text,
  ingest_status
)
VALUES (
  '74000000-0000-0000-0000-000000000001',
  'legislation',
  'Test Kanunu Madde 1',
  'test-law-1',
  'TBMM',
  'Test kanun maddesi metni.',
  'ready'
);

INSERT INTO legislation_details (
  legal_source_id,
  legislation_type,
  law_name,
  law_no,
  article_no
)
VALUES (
  '74000000-0000-0000-0000-000000000001',
  'law',
  'Test Kanunu',
  '9999',
  '1'
);

INSERT INTO legal_chunks (
  id,
  legal_source_id,
  chunk_index,
  content,
  token_count
)
VALUES (
  '74100000-0000-0000-0000-000000000001',
  '74000000-0000-0000-0000-000000000001',
  0,
  'Test Kanunu Madde 1 kaynak metni.',
  7
);

INSERT INTO conversations (id, project_id, created_by, title)
VALUES (
  '75000000-0000-0000-0000-000000000001',
  '72000000-0000-0000-0000-000000000001',
  '70000000-0000-0000-0000-000000000001',
  'V2 test konuşması'
);

INSERT INTO messages (id, conversation_id, role, content)
VALUES
  (
    '75100000-0000-0000-0000-000000000001',
    '75000000-0000-0000-0000-000000000001',
    'user',
    'Test sorusu'
  ),
  (
    '75100000-0000-0000-0000-000000000002',
    '75000000-0000-0000-0000-000000000001',
    'assistant',
    'Kaynaklı test cevabı [1] [2]'
  );

INSERT INTO citations (
  id,
  message_id,
  legal_chunk_id,
  citation_order,
  marker,
  source_title,
  snippet,
  relevance_score
)
VALUES (
  '76000000-0000-0000-0000-000000000001',
  '75100000-0000-0000-0000-000000000002',
  '74100000-0000-0000-0000-000000000001',
  1,
  '[1]',
  'Test Kanunu Madde 1',
  'Test Kanunu Madde 1 kaynak metni.',
  0.95
);

INSERT INTO citations (
  id,
  message_id,
  document_chunk_id,
  citation_order,
  marker,
  source_title,
  snippet,
  relevance_score
)
VALUES (
  '76000000-0000-0000-0000-000000000002',
  '75100000-0000-0000-0000-000000000002',
  '73100000-0000-0000-0000-000000000001',
  2,
  '[2]',
  'test-belgesi.pdf',
  'Test belgesinin kaynak olarak kullanılacak metni.',
  0.90
);

INSERT INTO saved_legal_sources (user_id, legal_source_id, note)
VALUES (
  '70000000-0000-0000-0000-000000000001',
  '74000000-0000-0000-0000-000000000001',
  'Test favorisi'
);

INSERT INTO activity_logs (
  actor_user_id,
  action,
  entity_type,
  entity_id,
  project_id
)
VALUES (
  '70000000-0000-0000-0000-000000000001',
  'citation.create',
  'message',
  '75100000-0000-0000-0000-000000000002',
  '72000000-0000-0000-0000-000000000001'
);

DO $$
DECLARE
  rejected BOOLEAN;
BEGIN
  rejected := FALSE;
  BEGIN
    INSERT INTO project_members (project_id, user_id, member_role)
    VALUES (
      '72000000-0000-0000-0000-000000000001',
      '70000000-0000-0000-0000-000000000003',
      'owner'
    );
  EXCEPTION
    WHEN unique_violation THEN
      rejected := TRUE;
  END;
  IF NOT rejected THEN
    RAISE EXCEPTION 'İkinci proje sahibi reddedilmedi.';
  END IF;

  rejected := FALSE;
  BEGIN
    INSERT INTO citations (
      message_id,
      document_chunk_id,
      legal_chunk_id,
      citation_order,
      source_title
    )
    VALUES (
      '75100000-0000-0000-0000-000000000002',
      '73100000-0000-0000-0000-000000000001',
      '74100000-0000-0000-0000-000000000001',
      3,
      'Geçersiz çift hedef'
    );
  EXCEPTION
    WHEN check_violation THEN
      rejected := TRUE;
  END;
  IF NOT rejected THEN
    RAISE EXCEPTION 'Çift hedefli citation reddedilmedi.';
  END IF;

  rejected := FALSE;
  BEGIN
    INSERT INTO citations (
      message_id,
      legal_chunk_id,
      citation_order,
      source_title
    )
    VALUES (
      '75100000-0000-0000-0000-000000000001',
      '74100000-0000-0000-0000-000000000001',
      3,
      'User mesajı için geçersiz citation'
    );
  EXCEPTION
    WHEN raise_exception THEN
      rejected := TRUE;
  END;
  IF NOT rejected THEN
    RAISE EXCEPTION 'User mesajına citation eklenmesi reddedilmedi.';
  END IF;
END;
$$;

CREATE ROLE nhr_rls_test NOLOGIN;
GRANT USAGE ON SCHEMA public TO nhr_rls_test;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nhr_rls_test;

SET LOCAL ROLE nhr_rls_test;
SET LOCAL app.user_id = '70000000-0000-0000-0000-000000000001';

DO $$
BEGIN
  IF (SELECT count(*) FROM projects) <> 1 THEN
    RAISE EXCEPTION 'Proje sahibi RLS üzerinden projesini göremedi.';
  END IF;
END;
$$;

SET LOCAL app.user_id = '70000000-0000-0000-0000-000000000002';

DO $$
BEGIN
  IF (SELECT count(*) FROM projects) <> 1 THEN
    RAISE EXCEPTION 'Proje editörü RLS üzerinden projesini göremedi.';
  END IF;
END;
$$;

SET LOCAL app.user_id = '70000000-0000-0000-0000-000000000003';

DO $$
BEGIN
  IF (SELECT count(*) FROM projects) <> 0 THEN
    RAISE EXCEPTION 'Yetkisiz kullanıcı RLS üzerinden projeyi görebildi.';
  END IF;

  IF (SELECT count(*) FROM documents) <> 0 THEN
    RAISE EXCEPTION 'Yetkisiz kullanıcı RLS üzerinden belgeyi görebildi.';
  END IF;

  IF (SELECT count(*) FROM conversations) <> 0 THEN
    RAISE EXCEPTION 'Yetkisiz kullanıcı RLS üzerinden konuşmayı görebildi.';
  END IF;
END;
$$;

RESET ROLE;
ROLLBACK;
