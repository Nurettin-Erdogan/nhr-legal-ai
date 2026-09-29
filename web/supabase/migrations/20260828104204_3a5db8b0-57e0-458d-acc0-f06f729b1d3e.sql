CREATE TABLE public.mevzuat (
  id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  mevzuat_id text NOT NULL,
  mevzuat_no text,
  adi text NOT NULL,
  tertip integer,
  tur text,
  resmi_gazete_tarihi timestamptz,
  resmi_gazete_sayisi text,
  kaynak_url text,
  madde_listesi jsonb NOT NULL DEFAULT '[]'::jsonb,
  tam_metin text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX mevzuat_mevzuat_id_key ON public.mevzuat (mevzuat_id);
CREATE INDEX mevzuat_adi_idx ON public.mevzuat (adi);
CREATE INDEX mevzuat_tur_idx ON public.mevzuat (tur);
CREATE INDEX mevzuat_rg_tarihi_idx ON public.mevzuat (resmi_gazete_tarihi);

GRANT SELECT ON public.mevzuat TO anon;
GRANT SELECT ON public.mevzuat TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.mevzuat TO service_role;

ALTER TABLE public.mevzuat ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Mevzuat herkese açık okunabilir" ON public.mevzuat
  FOR SELECT TO anon, authenticated
  USING (true);

CREATE POLICY "Service role mevzuatı yönetir" ON public.mevzuat
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_mevzuat_updated_at
BEFORE UPDATE ON public.mevzuat
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();