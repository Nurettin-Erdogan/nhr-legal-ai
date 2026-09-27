# NHR Legal AI — web

React 19 + TanStack Start/Router + Vite arayüzü. Eski Next.js `app/` ağacının
yerini `src/routes/` alır. Geliştirme dalı `feature/legal-ai`; main'e push/merge
ve yayımlanmış geçmişi yeniden yazma yapılmaz.

## Yerel çalıştırma

Repo kökünde FastAPI ve PostgreSQL'i [ana kurulumla](../docs/database-setup.md)
başlatın. Büro ekranları için `026_office_workspace.sql` migration'ı gerekir;
`web/supabase/migrations` eski tasarım arşividir, PostgreSQL'e uygulanmaz.

Node.js 22.12+ kullanın. Repo kökünden:

```powershell
cd web
npm ci
npm run dev -- --host 127.0.0.1 --port 3000
```

`http://localhost:3000/auth` üzerinden giriş yapın. Varsayılan backend
`http://localhost:8766`. Başka adres için `web/.env.local` içinde
`VITE_API_URL` tanımlayıp frontend'i yeniden başlatın/build edin. Frontend ve
backend'de aynı hostname'i kullanın; gerekli origin backend `CORS_ORIGINS`
listesinde olmalı. Kimlik doğrulama HttpOnly cookie ve bellekteki token ile
yapılır; AI anahtarı, veritabanı şifresi veya başka secret **VITE_** değişkenine
konulmaz (tarayıcıya açık olur).

## Kontroller

```powershell
npm run typecheck
npm test
npm run build
```

`npm run preview` derlemeyi yerelde denemek içindir. İnternete yayın; HTTPS,
cookie/CORS, hız limitleri ve yedeklemeler ayrıca yapılandırılmadan hazır değildir.

## Bağlantılar ve sınırlar

- Hukuk asistanı `/api/ai/answer/progress`; sohbetler `/api/conversations`.
- Büro verileri `/api/office/*`, PostgreSQL RLS ile kullanıcıya ayrılır.
  `integrations/supabase/client.ts` yalnız yerel API uyumluluk katmanıdır.
- RAG aday sayısı, modele verilen belge ve atıf sayısı farklıdır; ekrandaki
  aday sayısı tüm korpusun sayısı değildir. Eski sohbetlere sayaç uydurulmaz.
- Büro belge üretiminde kaynak denetimini geçmeyen metin gösterilmez.
  Bu katı kontrol nedeniyle bazı taslak/analiz istekleri reddedilebilir.
- Ödeme/abonelik ve sosyal giriş henüz bağlı değildir. OCR ayrıca Tesseract,
  Türkçe dil verisi, Pillow ve pytesseract gerektirir.
- UYAP uzantıları yalnız yetkili kullanıcının oturumunda kullanılmalıdır;
  bu yayında canlı UYAP oturumuyla uçtan uca test yapılmamıştır.
