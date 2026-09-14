\set ON_ERROR_STOP on

INSERT INTO users (id, email, password_hash, full_name)
VALUES
  ('10000000-0000-0000-0000-000000000001', 'owner@example.test', 'test-hash', 'Test Owner'),
  ('10000000-0000-0000-0000-000000000002', 'member@example.test', 'test-hash', 'Test Member');

INSERT INTO projects (id, user_id, name, description)
VALUES (
  '20000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'V1 Test Dosyası',
  'V2 migration backfill testi'
);

INSERT INTO documents (
  id,
  project_id,
  user_id,
  file_name,
  mime_type,
  storage_key,
  status
)
VALUES (
  '30000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'dilekce.pdf',
  'application/pdf',
  'test/dilekce.pdf',
  'ready'
);

INSERT INTO document_chunks (
  id,
  document_id,
  chunk_index,
  content
)
VALUES (
  '31000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001',
  0,
  'Kullanıcı belgesinden örnek metin.'
);

INSERT INTO conversations (id, project_id, user_id, title)
VALUES (
  '40000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'V1 test konuşması'
);

INSERT INTO messages (id, conversation_id, role, content, model_name)
VALUES (
  '41000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  'assistant',
  'Kaynak gösterimli test cevabı.',
  'test-model'
);

INSERT INTO legal_sources (
  id,
  source_type,
  title,
  source_url,
  law_name,
  article_no,
  raw_text
)
VALUES (
  '50000000-0000-0000-0000-000000000001',
  'mevzuat',
  'Türk Borçlar Kanunu Madde 1',
  'https://example.test/mevzuat/1',
  'Türk Borçlar Kanunu',
  '1',
  'Sözleşme, tarafların iradelerini karşılıklı açıklamalarıyla kurulur.'
);

INSERT INTO legal_sources (
  id,
  source_type,
  title,
  source_url,
  court_name,
  chamber,
  docket_no,
  decision_no,
  decision_date,
  raw_text
)
VALUES (
  '50000000-0000-0000-0000-000000000002',
  'ictihat',
  'Yargıtay Test Kararı',
  'https://example.test/karar/1',
  'Yargıtay',
  '9. Hukuk Dairesi',
  '2024/100',
  '2025/200',
  '2025-01-15',
  'Örnek mahkeme kararı metni.'
);

INSERT INTO legal_chunks (id, legal_source_id, chunk_index, content)
VALUES
  (
    '51000000-0000-0000-0000-000000000001',
    '50000000-0000-0000-0000-000000000001',
    0,
    'Türk Borçlar Kanunu Madde 1 metni.'
  ),
  (
    '51000000-0000-0000-0000-000000000002',
    '50000000-0000-0000-0000-000000000002',
    0,
    'Yargıtay kararının gerekçe bölümü.'
  );

INSERT INTO citations (
  id,
  message_id,
  legal_source_id,
  legal_chunk_id,
  quoted_text,
  relevance_score
)
VALUES (
  '60000000-0000-0000-0000-000000000001',
  '41000000-0000-0000-0000-000000000001',
  '50000000-0000-0000-0000-000000000001',
  '51000000-0000-0000-0000-000000000001',
  'TBK Madde 1',
  0.95
);

INSERT INTO citations (
  id,
  message_id,
  document_chunk_id,
  quoted_text,
  relevance_score
)
VALUES (
  '60000000-0000-0000-0000-000000000002',
  '41000000-0000-0000-0000-000000000001',
  '31000000-0000-0000-0000-000000000001',
  'Kullanıcı belgesinden örnek metin.',
  0.90
);
