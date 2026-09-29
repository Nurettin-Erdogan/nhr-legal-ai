CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE public.basvurular (
  id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  ad_soyad TEXT NOT NULL,
  telefon TEXT,
  eposta TEXT,
  hukuk_alani TEXT,
  konu TEXT NOT NULL,
  sohbet_ozeti TEXT,
  durum TEXT NOT NULL DEFAULT 'yeni',
  atanan_id UUID,
  notlar TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX basvurular_created_at_idx ON public.basvurular (created_at DESC);
CREATE INDEX basvurular_durum_idx ON public.basvurular (durum);

GRANT INSERT ON public.basvurular TO anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.basvurular TO authenticated;
GRANT ALL ON public.basvurular TO service_role;

ALTER TABLE public.basvurular ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Herkes basvuru olusturabilir (anon)"
  ON public.basvurular FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY "Girisli kullanicilar basvuru olusturabilir"
  ON public.basvurular FOR INSERT TO authenticated WITH CHECK (true);

CREATE POLICY "Girisli kullanicilar basvurulari gorur"
  ON public.basvurular FOR SELECT TO authenticated USING (true);

CREATE POLICY "Girisli kullanicilar basvuru guncelleyebilir"
  ON public.basvurular FOR UPDATE TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "Adminler basvuru silebilir"
  ON public.basvurular FOR DELETE TO authenticated USING (public.has_role(auth.uid(), 'admin'));

CREATE TRIGGER update_basvurular_updated_at
  BEFORE UPDATE ON public.basvurular
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();