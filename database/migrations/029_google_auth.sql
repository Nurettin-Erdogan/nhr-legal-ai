-- Google subject is stable; email is not used as an automatic account link.
CREATE TABLE IF NOT EXISTS auth_google_identities (
  user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  google_subject TEXT NOT NULL UNIQUE,
  linked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT auth_google_subject_nonempty CHECK (length(google_subject) BETWEEN 1 AND 255)
);

-- Only the admin-side authentication flow accesses this table. Runtime role
-- receives no policy and cannot enumerate Google identities.
ALTER TABLE auth_google_identities ENABLE ROW LEVEL SECURITY;
