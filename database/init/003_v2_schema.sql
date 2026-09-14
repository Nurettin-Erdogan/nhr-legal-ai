BEGIN;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

ALTER TABLE users
  ADD COLUMN status TEXT NOT NULL DEFAULT 'active',
  ADD COLUMN last_login_at TIMESTAMPTZ,
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT users_status_check
    CHECK (status IN ('active', 'inactive', 'suspended'));

CREATE TABLE roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO roles (code, name, description)
VALUES
  ('admin', 'Yönetici', 'Platform, kullanıcı ve hukuk korpusu yönetimi'),
  ('lawyer', 'Avukat', 'Hukuk dosyası, belge ve araştırma işlemleri'),
  ('assistant', 'Asistan', 'Yetkili olduğu hukuk dosyalarında çalışma'),
  ('viewer', 'Görüntüleyici', 'Yetkili olduğu kayıtları salt okunur görüntüleme');

CREATE TABLE user_roles (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  granted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_type TEXT NOT NULL DEFAULT 'individual',
  display_name TEXT NOT NULL,
  identity_number_ciphertext BYTEA,
  identity_number_last4 TEXT,
  email TEXT,
  phone TEXT,
  address TEXT,
  notes TEXT,
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT clients_type_check
    CHECK (client_type IN ('individual', 'corporate')),
  CONSTRAINT clients_identity_last4_check
    CHECK (
      identity_number_last4 IS NULL
      OR identity_number_last4 ~ '^[0-9]{4}$'
    )
);

ALTER TABLE projects
  ADD COLUMN client_id UUID REFERENCES clients(id) ON DELETE SET NULL,
  ADD COLUMN created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN matter_type TEXT NOT NULL DEFAULT 'case',
  ADD COLUMN status TEXT NOT NULL DEFAULT 'active',
  ADD COLUMN reference_no TEXT,
  ADD COLUMN court_name TEXT,
  ADD COLUMN chamber TEXT,
  ADD COLUMN docket_no TEXT,
  ADD COLUMN decision_no TEXT,
  ADD COLUMN opened_on DATE,
  ADD COLUMN closed_on DATE,
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT projects_matter_type_check
    CHECK (matter_type IN ('case', 'enforcement', 'consultancy', 'research', 'other')),
  ADD CONSTRAINT projects_status_check
    CHECK (status IN ('active', 'on_hold', 'closed', 'archived')),
  ADD CONSTRAINT projects_dates_check
    CHECK (closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on);

UPDATE projects
SET created_by = user_id;

CREATE TABLE project_members (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  member_role TEXT NOT NULL DEFAULT 'viewer',
  added_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (project_id, user_id),
  CONSTRAINT project_members_role_check
    CHECK (member_role IN ('owner', 'editor', 'viewer'))
);

INSERT INTO project_members (project_id, user_id, member_role, added_by)
SELECT id, user_id, 'owner', user_id
FROM projects;

CREATE UNIQUE INDEX uq_project_members_single_owner
  ON project_members (project_id)
  WHERE member_role = 'owner';

DROP INDEX idx_projects_user_id;
ALTER TABLE projects DROP CONSTRAINT projects_user_id_fkey;
ALTER TABLE projects DROP COLUMN user_id;

DROP INDEX idx_documents_user_id;
ALTER TABLE documents DROP CONSTRAINT documents_user_id_fkey;
ALTER TABLE documents RENAME COLUMN user_id TO uploaded_by;
ALTER TABLE documents
  ADD CONSTRAINT documents_uploaded_by_fkey
    FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE RESTRICT,
  ADD COLUMN file_size BIGINT,
  ADD COLUMN checksum_sha256 TEXT,
  ADD COLUMN storage_bucket TEXT,
  ADD COLUMN processing_error TEXT,
  ADD COLUMN processed_at TIMESTAMPTZ,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT documents_status_check
    CHECK (status IN ('uploaded', 'processing', 'ready', 'failed')),
  ADD CONSTRAINT documents_file_size_check
    CHECK (file_size IS NULL OR file_size >= 0),
  ADD CONSTRAINT documents_checksum_check
    CHECK (
      checksum_sha256 IS NULL
      OR checksum_sha256 ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE document_chunks
  ADD COLUMN page_number INT,
  ADD COLUMN section_title TEXT,
  ADD COLUMN char_start INT,
  ADD COLUMN char_end INT,
  ADD COLUMN token_count INT,
  ADD COLUMN content_hash TEXT,
  ADD COLUMN embedding_model TEXT,
  ADD COLUMN embedding_created_at TIMESTAMPTZ,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN search_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('turkish'::regconfig, content)) STORED,
  ADD CONSTRAINT document_chunks_index_check
    CHECK (chunk_index >= 0),
  ADD CONSTRAINT document_chunks_page_check
    CHECK (page_number IS NULL OR page_number >= 1),
  ADD CONSTRAINT document_chunks_char_range_check
    CHECK (
      (char_start IS NULL AND char_end IS NULL)
      OR (
        char_start IS NOT NULL
        AND char_end IS NOT NULL
        AND char_start >= 0
        AND char_end >= char_start
      )
    ),
  ADD CONSTRAINT document_chunks_token_count_check
    CHECK (token_count IS NULL OR token_count >= 0);

DROP INDEX idx_conversations_user_id;
ALTER TABLE conversations DROP CONSTRAINT conversations_user_id_fkey;
ALTER TABLE conversations RENAME COLUMN user_id TO created_by;
ALTER TABLE conversations
  ADD CONSTRAINT conversations_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE conversations DROP CONSTRAINT conversations_project_id_fkey;
ALTER TABLE conversations
  ADD CONSTRAINT conversations_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

ALTER TABLE messages
  ADD COLUMN token_count INT,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT messages_token_count_check
    CHECK (token_count IS NULL OR token_count >= 0);

ALTER TABLE legal_sources
  ADD COLUMN external_id TEXT,
  ADD COLUMN authority TEXT,
  ADD COLUMN jurisdiction TEXT NOT NULL DEFAULT 'TR',
  ADD COLUMN published_at DATE,
  ADD COLUMN effective_from DATE,
  ADD COLUMN effective_to DATE,
  ADD COLUMN version_label TEXT,
  ADD COLUMN content_hash TEXT,
  ADD COLUMN ingest_status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN last_ingested_at TIMESTAMPTZ,
  ADD COLUMN deleted_at TIMESTAMPTZ,
  ADD COLUMN deleted_by UUID REFERENCES users(id) ON DELETE SET NULL,
  ADD CONSTRAINT legal_sources_effective_dates_check
    CHECK (
      effective_to IS NULL
      OR effective_from IS NULL
      OR effective_to >= effective_from
    ),
  ADD CONSTRAINT legal_sources_ingest_status_check
    CHECK (ingest_status IN ('pending', 'processing', 'ready', 'failed'));

UPDATE legal_sources
SET metadata = metadata || jsonb_build_object(
  'legacy_legal_fields',
  jsonb_strip_nulls(
    jsonb_build_object(
      'court_name', court_name,
      'chamber', chamber,
      'decision_no', decision_no,
      'docket_no', docket_no,
      'decision_date', decision_date,
      'law_name', law_name,
      'article_no', article_no
    )
  )
)
WHERE court_name IS NOT NULL
   OR chamber IS NOT NULL
   OR decision_no IS NOT NULL
   OR docket_no IS NOT NULL
   OR decision_date IS NOT NULL
   OR law_name IS NOT NULL
   OR article_no IS NOT NULL;

UPDATE legal_sources
SET metadata = metadata || jsonb_build_object('legacy_source_type', source_type)
WHERE lower(source_type) NOT IN (
  'legislation',
  'law',
  'regulation',
  'statute',
  'mevzuat',
  'court_decision',
  'decision',
  'case_law',
  'ictihat',
  'içtihat',
  'other'
);

UPDATE legal_sources
SET source_type = CASE
  WHEN lower(source_type) IN ('legislation', 'law', 'regulation', 'statute', 'mevzuat')
    THEN 'legislation'
  WHEN lower(source_type) IN ('court_decision', 'decision', 'case_law', 'ictihat', 'içtihat')
    THEN 'court_decision'
  ELSE 'other'
END;

UPDATE legal_sources
SET ingest_status = 'ready',
    last_ingested_at = COALESCE(updated_at, created_at)
WHERE raw_text IS NOT NULL AND btrim(raw_text) <> '';

ALTER TABLE legal_sources
  ADD CONSTRAINT legal_sources_type_check
    CHECK (source_type IN ('legislation', 'court_decision', 'other'));

CREATE TABLE legislation_details (
  legal_source_id UUID PRIMARY KEY
    REFERENCES legal_sources(id) ON DELETE CASCADE,
  legislation_type TEXT NOT NULL DEFAULT 'law',
  law_name TEXT NOT NULL,
  law_no TEXT,
  article_no TEXT,
  article_title TEXT,
  paragraph_no TEXT,
  clause_no TEXT,
  official_gazette_no TEXT,
  official_gazette_date DATE,
  version_date DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT legislation_details_type_check
    CHECK (
      legislation_type IN (
        'constitution',
        'law',
        'decree',
        'regulation',
        'communique',
        'other'
      )
    )
);

CREATE TABLE court_decision_details (
  legal_source_id UUID PRIMARY KEY
    REFERENCES legal_sources(id) ON DELETE CASCADE,
  court_name TEXT NOT NULL,
  chamber TEXT,
  docket_no TEXT,
  decision_no TEXT,
  decision_date DATE,
  decision_type TEXT,
  outcome TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO legislation_details (
  legal_source_id,
  legislation_type,
  law_name,
  article_no
)
SELECT
  id,
  'law',
  COALESCE(NULLIF(btrim(law_name), ''), title),
  NULLIF(btrim(article_no), '')
FROM legal_sources
WHERE source_type = 'legislation';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM legal_sources
    WHERE source_type = 'court_decision'
      AND (court_name IS NULL OR btrim(court_name) = '')
  ) THEN
    RAISE EXCEPTION
      'Mahkeme kararı kaynaklarında court_name eksik; V2 migration öncesi veri temizliği gerekli.';
  END IF;
END;
$$;

INSERT INTO court_decision_details (
  legal_source_id,
  court_name,
  chamber,
  docket_no,
  decision_no,
  decision_date
)
SELECT
  id,
  btrim(court_name),
  NULLIF(btrim(chamber), ''),
  NULLIF(btrim(docket_no), ''),
  NULLIF(btrim(decision_no), ''),
  decision_date
FROM legal_sources
WHERE source_type = 'court_decision';

DROP INDEX idx_legal_sources_decision_date;
ALTER TABLE legal_sources
  DROP COLUMN court_name,
  DROP COLUMN chamber,
  DROP COLUMN decision_no,
  DROP COLUMN docket_no,
  DROP COLUMN decision_date,
  DROP COLUMN law_name,
  DROP COLUMN article_no;

ALTER TABLE legal_chunks
  ADD COLUMN section_title TEXT,
  ADD COLUMN paragraph_start INT,
  ADD COLUMN paragraph_end INT,
  ADD COLUMN token_count INT,
  ADD COLUMN content_hash TEXT,
  ADD COLUMN embedding_model TEXT,
  ADD COLUMN embedding_created_at TIMESTAMPTZ,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN search_vector TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('turkish'::regconfig, content)) STORED,
  ADD CONSTRAINT legal_chunks_index_check
    CHECK (chunk_index >= 0),
  ADD CONSTRAINT legal_chunks_paragraph_range_check
    CHECK (
      (paragraph_start IS NULL AND paragraph_end IS NULL)
      OR (
        paragraph_start IS NOT NULL
        AND paragraph_end IS NOT NULL
        AND paragraph_start >= 0
        AND paragraph_end >= paragraph_start
      )
    ),
  ADD CONSTRAINT legal_chunks_token_count_check
    CHECK (token_count IS NULL OR token_count >= 0);

ALTER TABLE citations
  ADD COLUMN citation_order INT,
  ADD COLUMN marker TEXT,
  ADD COLUMN source_title TEXT,
  ADD COLUMN source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM citations
    WHERE legal_source_id IS NOT NULL
      AND document_chunk_id IS NOT NULL
  ) THEN
    RAISE EXCEPTION
      'Document citation ile legal_source_id birlikte kullanılmış; belirsiz kayıtlar migration öncesi ayrıştırılmalı.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM citations
    WHERE num_nonnulls(document_chunk_id, legal_chunk_id) <> 1
  ) THEN
    RAISE EXCEPTION
      'Her V1 citation için tam bir document_chunk_id veya legal_chunk_id gerekli; keyfi chunk seçilmedi.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM citations AS citation
    JOIN legal_chunks AS chunk ON chunk.id = citation.legal_chunk_id
    WHERE citation.legal_source_id IS NOT NULL
      AND citation.legal_source_id <> chunk.legal_source_id
  ) THEN
    RAISE EXCEPTION
      'Bazı citations kayıtlarında legal_source_id ve legal_chunk_id birbiriyle uyuşmuyor.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM citations AS citation
    JOIN messages AS message ON message.id = citation.message_id
    WHERE message.role <> 'assistant'
  ) THEN
    RAISE EXCEPTION
      'Citation yalnızca assistant mesajına bağlanabilir; mevcut veride uyumsuz kayıt var.';
  END IF;
END;
$$;

WITH ranked AS (
  SELECT
    id,
    row_number() OVER (
      PARTITION BY message_id
      ORDER BY created_at, id
    )::INT AS position
  FROM citations
)
UPDATE citations AS citation
SET citation_order = ranked.position
FROM ranked
WHERE ranked.id = citation.id;

UPDATE citations AS citation
SET source_title = COALESCE(
  (
    SELECT source.title
    FROM legal_chunks AS chunk
    JOIN legal_sources AS source ON source.id = chunk.legal_source_id
    WHERE chunk.id = citation.legal_chunk_id
  ),
  (
    SELECT document.file_name
    FROM document_chunks AS chunk
    JOIN documents AS document ON document.id = chunk.document_id
    WHERE chunk.id = citation.document_chunk_id
  )
);

ALTER TABLE citations DROP CONSTRAINT citations_legal_source_id_fkey;
ALTER TABLE citations DROP CONSTRAINT citations_document_chunk_id_fkey;
ALTER TABLE citations DROP CONSTRAINT citations_legal_chunk_id_fkey;
ALTER TABLE citations DROP COLUMN legal_source_id;
ALTER TABLE citations
  ALTER COLUMN citation_order SET NOT NULL,
  ALTER COLUMN source_title SET NOT NULL;
ALTER TABLE citations RENAME COLUMN quoted_text TO snippet;

ALTER TABLE citations
  ADD CONSTRAINT citations_document_chunk_id_fkey
    FOREIGN KEY (document_chunk_id) REFERENCES document_chunks(id) ON DELETE RESTRICT,
  ADD CONSTRAINT citations_legal_chunk_id_fkey
    FOREIGN KEY (legal_chunk_id) REFERENCES legal_chunks(id) ON DELETE RESTRICT,
  ADD CONSTRAINT citations_single_target_check
    CHECK (num_nonnulls(document_chunk_id, legal_chunk_id) = 1),
  ADD CONSTRAINT citations_order_check
    CHECK (citation_order > 0),
  ADD CONSTRAINT citations_relevance_score_check
    CHECK (
      relevance_score IS NULL
      OR relevance_score BETWEEN 0.0 AND 1.0
    ),
  ADD CONSTRAINT citations_message_order_unique
    UNIQUE (message_id, citation_order);

CREATE OR REPLACE FUNCTION enforce_citation_assistant_message()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM messages
    WHERE id = NEW.message_id
      AND role = 'assistant'
  ) THEN
    RAISE EXCEPTION 'Citation yalnızca assistant mesajına bağlanabilir.';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER citations_assistant_message_guard
BEFORE INSERT OR UPDATE OF message_id ON citations
FOR EACH ROW
EXECUTE FUNCTION enforce_citation_assistant_message();

CREATE TABLE saved_legal_sources (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  legal_source_id UUID NOT NULL REFERENCES legal_sources(id) ON DELETE CASCADE,
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, legal_source_id)
);

CREATE TABLE activity_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  entity_type TEXT,
  entity_id UUID,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  request_id UUID,
  ip_address INET,
  user_agent TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_active_status
  ON users (status)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_user_roles_role_id ON user_roles (role_id);
CREATE INDEX idx_clients_created_by ON clients (created_by);
CREATE INDEX idx_clients_active_name
  ON clients (lower(display_name))
  WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_created_by ON projects (created_by);
CREATE INDEX idx_projects_client_id ON projects (client_id);
CREATE INDEX idx_projects_active_status
  ON projects (status)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_project_members_user_id
  ON project_members (user_id, project_id);
CREATE INDEX idx_documents_uploaded_by ON documents (uploaded_by);
CREATE INDEX idx_documents_active_project
  ON documents (project_id, created_at DESC)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_processing
  ON documents (status, created_at)
  WHERE deleted_at IS NULL AND status IN ('uploaded', 'processing', 'failed');
CREATE INDEX idx_document_chunks_search_vector
  ON document_chunks USING GIN (search_vector);
CREATE INDEX idx_conversations_created_by ON conversations (created_by);
CREATE INDEX idx_conversations_active_project
  ON conversations (project_id, updated_at DESC)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_messages_conversation_created
  ON messages (conversation_id, created_at, id)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_legal_sources_active_type
  ON legal_sources (source_type, published_at DESC)
  WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX uq_legal_sources_external_id
  ON legal_sources (source_type, external_id)
  WHERE external_id IS NOT NULL;
CREATE INDEX idx_legislation_details_law_article
  ON legislation_details (law_no, article_no);
CREATE UNIQUE INDEX uq_legislation_details_version
  ON legislation_details (law_no, article_no, version_date)
  WHERE law_no IS NOT NULL
    AND article_no IS NOT NULL
    AND version_date IS NOT NULL;
CREATE INDEX idx_court_decision_lookup
  ON court_decision_details (
    lower(court_name),
    lower(COALESCE(chamber, '')),
    docket_no,
    decision_no,
    decision_date
  );
CREATE UNIQUE INDEX uq_court_decision_natural
  ON court_decision_details (
    lower(court_name),
    lower(COALESCE(chamber, '')),
    docket_no,
    decision_no
  )
  WHERE docket_no IS NOT NULL AND decision_no IS NOT NULL;
CREATE INDEX idx_legal_chunks_search_vector
  ON legal_chunks USING GIN (search_vector);
CREATE INDEX idx_citations_document_chunk_id
  ON citations (document_chunk_id)
  WHERE document_chunk_id IS NOT NULL;
CREATE INDEX idx_citations_legal_chunk_id
  ON citations (legal_chunk_id)
  WHERE legal_chunk_id IS NOT NULL;
CREATE INDEX idx_saved_legal_sources_source_id
  ON saved_legal_sources (legal_source_id);
CREATE INDEX idx_activity_logs_actor_created
  ON activity_logs (actor_user_id, created_at DESC);
CREATE INDEX idx_activity_logs_project_created
  ON activity_logs (project_id, created_at DESC);
CREATE INDEX idx_activity_logs_entity
  ON activity_logs (entity_type, entity_id);

CREATE TRIGGER users_set_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER roles_set_updated_at
BEFORE UPDATE ON roles
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER clients_set_updated_at
BEFORE UPDATE ON clients
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER projects_set_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER documents_set_updated_at
BEFORE UPDATE ON documents
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER document_chunks_set_updated_at
BEFORE UPDATE ON document_chunks
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER conversations_set_updated_at
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER messages_set_updated_at
BEFORE UPDATE ON messages
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER legal_sources_set_updated_at
BEFORE UPDATE ON legal_sources
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER legislation_details_set_updated_at
BEFORE UPDATE ON legislation_details
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER court_decision_details_set_updated_at
BEFORE UPDATE ON court_decision_details
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER legal_chunks_set_updated_at
BEFORE UPDATE ON legal_chunks
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER citations_set_updated_at
BEFORE UPDATE ON citations
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER saved_legal_sources_set_updated_at
BEFORE UPDATE ON saved_legal_sources
FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMIT;
