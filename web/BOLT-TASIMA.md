# bolt.new'a Taşıma Rehberi

Bu paket, projenin bolt.new'a aktarılmaya hazır halidir. `.env` dosyası
güvenlik nedeniyle **çıkarılmıştır**; yerine `.env.example` konmuştur.

## 1. GitHub'a yükle (önerilen yol)

bolt.new bir ZIP dosyasını doğrudan kabul etmez, ama bir GitHub deposunu açabilir.

1. github.com'da yeni bir **private** repo oluştur (örn. `hukuk-ai`).
2. Bu paketi bilgisayarında bir klasöre çıkar.
3. Terminalde klasörün içinde:

```bash
git init
git add .
git commit -m "ilk aktarım"
git branch -M main
git remote add origin https://github.com/KULLANICI_ADI/hukuk-ai.git
git push -u origin main
```

4. Tarayıcıda şu adresi aç:

```
https://bolt.new/github.com/KULLANICI_ADI/hukuk-ai
```

bolt.new depoyu içine alıp çalıştırmayı dener.

## 2. Ortam değişkenlerini gir

bolt.new içinde `.env.example` dosyasını `.env` olarak kopyala ve değerleri doldur:

| Değişken | Nerede kullanılır |
|---|---|
| `VITE_SUPABASE_URL` | Tarayıcı tarafı veritabanı bağlantısı |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Tarayıcı tarafı public anahtar |
| `VITE_SUPABASE_PROJECT_ID` | Proje kimliği |
| `SUPABASE_URL` | Sunucu tarafı bağlantı |
| `SUPABASE_PUBLISHABLE_KEY` | Sunucu tarafı public anahtar |
| `SUPABASE_SERVICE_ROLE_KEY` | Sunucu tarafı yetkili işlemler (yalnız sunucu!) |
| `LOVABLE_API_KEY` | Yapay zekâ (Gemini) çağrıları |
| `LOVABLE_CRON_SECRET` | Zamanlanmış mevzuat güncelleme ucu |

Bu değerler senin kendi Supabase projenden gelir. Lovable Cloud'daki mevcut
veritabanına bağlanmak istiyorsan aynı değerleri kullanabilirsin; sıfırdan
kendi Supabase projeni kuracaksan `supabase/migrations/` altındaki SQL
dosyalarını sırayla çalıştır.

## 3. Yapay zekâ tarafı

`LOVABLE_API_KEY` Lovable AI Gateway'e aittir. bolt.new'da bu anahtar
çalışmaya devam eder, ancak dışarıda uzun vadede kendi Google Gemini
anahtarını kullanmak istersen `src/lib/ai.server.ts` içindeki uç noktayı
Google'ın kendi API adresine çevirmen gerekir.

## 4. Dikkat edilecekler

- Proje **TanStack Start** (SSR + sunucu fonksiyonları) üzerine kuruludur.
  bolt.new bunu çalıştırabilir, ancak salt statik bir çıktı üretmek
  istersen `/api` uçları ve sunucu fonksiyonları çalışmaz.
- `SUPABASE_SERVICE_ROLE_KEY` asla tarayıcıya veya herkese açık bir repoya
  konmamalı.
- Kurulum: `npm install` (veya `bun install`), ardından `npm run dev`.

## Klasör yapısı

- `src/routes/` — sayfalar ve API uçları
- `src/components/` — arayüz bileşenleri
- `src/lib/` — sunucu fonksiyonları, mevzuat/AI mantığı
- `supabase/migrations/` — veritabanı şeması
- `scripts/` — mevzuat yükleme (ETL) betikleri
