-- Fresh database counterpart of migrations/029_google_auth.sql.
CREATE TABLE IF NOT EXISTS auth_google_identities (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  google_subject TEXT NOT NULL UNIQUE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT auth_google_subject_nonempty CHECK (length(google_subject) BETWEEN 1 AND 255)
);

ALTER TABLE auth_google_identities ENABLE ROW LEVEL SECURITY;
