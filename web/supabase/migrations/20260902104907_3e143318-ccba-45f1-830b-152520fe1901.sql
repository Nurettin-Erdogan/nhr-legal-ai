CREATE TABLE public.uyap_ingest_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  token text NOT NULL UNIQUE,
  label text,
  last_used_at timestamptz,
  revoked boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX uyap_ingest_tokens_owner_idx ON public.uyap_ingest_tokens(owner_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.uyap_ingest_tokens TO authenticated;
GRANT ALL ON public.uyap_ingest_tokens TO service_role;

ALTER TABLE public.uyap_ingest_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Owners manage their ingest tokens"
ON public.uyap_ingest_tokens FOR ALL TO authenticated
USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id);