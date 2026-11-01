CREATE TABLE public.case_documents (
  id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  case_id UUID REFERENCES public.cases(id) ON DELETE SET NULL,
  client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  mime_type TEXT,
  size_bytes BIGINT,
  source TEXT NOT NULL DEFAULT 'manual',
  uyap_file_no TEXT,
  uyap_birim TEXT,
  doc_date DATE,
  doc_type TEXT,
  tags TEXT[],
  notes TEXT,
  content_excerpt TEXT,
  sync_run_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.case_documents TO authenticated;
GRANT ALL ON public.case_documents TO service_role;
ALTER TABLE public.case_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Kendi belgelerini gorur" ON public.case_documents FOR SELECT TO authenticated USING (auth.uid() = owner_id);
CREATE POLICY "Kendi belgesini ekler" ON public.case_documents FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Kendi belgesini guncelller" ON public.case_documents FOR UPDATE TO authenticated USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Kendi belgesini siler" ON public.case_documents FOR DELETE TO authenticated USING (auth.uid() = owner_id);

CREATE INDEX idx_case_documents_owner ON public.case_documents(owner_id, created_at DESC);
CREATE INDEX idx_case_documents_case ON public.case_documents(case_id);
CREATE UNIQUE INDEX idx_case_documents_path ON public.case_documents(storage_path);

CREATE TRIGGER trg_case_documents_updated_at BEFORE UPDATE ON public.case_documents
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.uyap_sync_runs (
  id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running',
  archive_name TEXT,
  found_count INTEGER NOT NULL DEFAULT 0,
  inserted_count INTEGER NOT NULL DEFAULT 0,
  skipped_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  duration_ms INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.uyap_sync_runs TO authenticated;
GRANT ALL ON public.uyap_sync_runs TO service_role;
ALTER TABLE public.uyap_sync_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Kendi sync kayitlarini gorur" ON public.uyap_sync_runs FOR SELECT TO authenticated USING (auth.uid() = owner_id);
CREATE POLICY "Kendi sync kaydini ekler" ON public.uyap_sync_runs FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Kendi sync kaydini guncelller" ON public.uyap_sync_runs FOR UPDATE TO authenticated USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id);
CREATE POLICY "Kendi sync kaydini siler" ON public.uyap_sync_runs FOR DELETE TO authenticated USING (auth.uid() = owner_id);

CREATE INDEX idx_uyap_sync_runs_owner ON public.uyap_sync_runs(owner_id, created_at DESC);

CREATE TRIGGER trg_uyap_sync_runs_updated_at BEFORE UPDATE ON public.uyap_sync_runs
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE POLICY "Kendi klasorundeki dosyalari gorur" ON storage.objects FOR SELECT TO authenticated
USING (bucket_id = 'case-files' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Kendi klasorune yukler" ON storage.objects FOR INSERT TO authenticated
WITH CHECK (bucket_id = 'case-files' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Kendi dosyasini guncelller" ON storage.objects FOR UPDATE TO authenticated
USING (bucket_id = 'case-files' AND auth.uid()::text = (storage.foldername(name))[1])
WITH CHECK (bucket_id = 'case-files' AND auth.uid()::text = (storage.foldername(name))[1]);

CREATE POLICY "Kendi dosyasini siler" ON storage.objects FOR DELETE TO authenticated
USING (bucket_id = 'case-files' AND auth.uid()::text = (storage.foldername(name))[1]);