# Mevzuat Entegrasyonu — Resmî Kanun Veritabanı Bağlantısı

## Amaç

JURISAI'nin cevaplarını gerçek, güncel, resmî Türk mevzuatına (kanun metinleri) dayandırmak.
Mevcut durumda tüm cevaplar AI modelinin kendi bilgisiyle üretiliyor; bu da halüsinasyon riski
taşıyor. Bu plan, kanun metinlerini resmî kaynaktan çekip kendi veritabanına kopyalar ve AI'ın
cevaplarını bu güncel maddelere dayandırmasını sağlar.

## Veri kaynağı

Adalet Bakanlığı'nın mevzuat servisi (`bedesten.adalet.gov.tr/mevzuat`). Sandbox'ta doğrulandı,
çalışıyor ve güncel veri dönüyor. Sağladığı uç noktalar:

- `/searchDocuments` — kanun/mevzuat arama ve listeleme (Resmi Gazete tarihli, güncel)
- `/getDocumentContent` — tam metin (HTML, base64, Windows-1254)
- `/mevzuatMaddeTree` — madde ağacı (madde no + başlık + id)

Kanun metinleri Türk hukukunda kamu malıdır (FSEK m.2/1); metni yayınlamak güvenlidir.
Her kayıtta orijinal kaynak linki ve "resmî metin için doğrulayınız" ibaresi tutulur.

## Yapılacak işler

### 1. Veritabanı — yeni `mevzuat` tablosu

Yeni bir `public.mevzuat` tablosu oluşturulur:

- `id` (uuid, PK)
- `mevzuat_id` (resmî servis id, benzersiz) — `/searchDocuments`'tan gelen id
- `mevzuat_no` — kanun numarası (örn. 4721)
- `adi` — kanun adı (örn. "Türk Medeni Kanunu")
- `tertip`, `tur` — mevzuat türü (KANUN, KHK, YÖNETMELİK...)
- `resmi_gazete_tarihi`, `resmi_gazete_sayisi`
- `kaynak_url` — mevzuat.gov.tr'ye orijinal link
- `madde_listesi` (jsonb) — madde ağacı (madde no + başlık + madde id)
- `tam_metin` (text) — HTML'den temizlenmiş düz metin
- `metadata`, `created_at`, `updated_at`

Erişim: `anon` SELECT yalnız (herkese açık okuma, kanun metinleri kamu malı);
`authenticated` ve `service_role` da SELECT. Yazma yalnız `service_role` (ETL işi).

RLS: anon + authenticated için `USING (true)` SELECT politikası; yazma yok (yalnız service_role).

### 2. Mevzuat istemcisi (`src/lib/mevzuat.server.ts`)

Adalet Bakanlığı servisine çağrı atan sunucu-tarafı modül:

- `searchDocuments(...)` — mevzuat listesi/arama
- `getDocumentContent(id)` — tam metni çek, Windows-1254 → UTF-8, HTML → düz metin
- `getMaddeTree(id)` — madde ağacı
- `mevzuatTypes()` — tür listesi

Rate-limit'e saygılı: istekler arasında küçük gecikme, kimliği gizleme yok,
makul User-Agent. Ayrıca sunucu-fonksiyon başına mevzuat indeksini arayan bir
`searchMevzuat(query)` sunucu fonksiyonu.

### 3. ETL — mevzuat yükleme ve otomatik güncelleme

`src/lib/mevzuat.etl.server.ts` içinde çalıştırılabilir ETL:

- **İlk yükleme**: tüm güncel mevzuatı sayfalayarak çeker, her belge için madde
  ağacı + tam metin indirir, `mevzuat` tablosuna kopyalar. Büyük ve yavaş bir
  iş olduğu için kademeli (chunk) yapılır.
- **Güncelleme**: zamanlayıcı ile düzenli çalışır; yeni/Değişen kanunları (Resmi
  Gazete tarihine göre) tespit edip sadece onları günceller. Otomatik güncel
  kalır.

ETL, `requireSupabaseAuth` gerektirmez — yalnız service-role ile yazar; tetiklenme
yolu admin panelinden manuel + düzenli otomatik.

### 4. AI + mevzuat bağlamı (RAG) — vatandaş sohbeti

`/api/public/citizen-chat` akışı değiştirilir:

1. Kullanıcı sorusu alınır.
2. `mevzuat` tablosunda metin araması yapılır (`websearch` / keyword), en ilgili
   madde metinleri seçilir.
3. Bu maddeler AI'a **bağlam** olarak eklenir (sistem prompt'unun yanına):
   "İlgili kanun maddeleri: ... (kaynak linki ile)".
4. AI, güncel maddeye dayanarak cevap yazar ve kaynağa link verir.
5. Halüsinasyonu azaltır; cevap artık gerçek maddeye dayanır.

Mevzuat bulunamazsa eski akış devam eder (AI kendi bilgisiyle yazar, uyarı koyar).

### 5. Avukat paneli bağlamı (isteğe bağlı ikinci adım)

Aynı mevzuat bağlamı, avukat modüllerine (`runAiLegal`) de eklenir — böylece
hukuki araştırma ve içtihat modülleri de güncel kanun maddelerine dayanır.

## Teknik notlar

- Mevzuat metinleri Windows-1254 kodlu HTML gelir; UTF-8'e çevrilir, HTML
  etiketleri temizlenir.
- Tam metin büyük olduğu için hem tam metin hem madde bazlı indeks tutulur;
  AI bağlamına sadece ilgili madde(ler) verilir (tüm metin değil) — token tasarrufu.
- Mevzuat araması için Postgres `textSearch` (websearch) kullanılır.
- Otomatik güncelleme için Lovable zamanlayıcı (cron) kullanılır.
- İlk yükleme "tüm mevzuat" olacak şekilde seçildi; kademeli ve rate-limit'e
  saygılı çalışır, tek seferde değil.

## Doğrulama

- `bunx tsgo --noEmit` geçer.
- Mevzuat ETL'i çalışır ve `mevzuat` tablosuna kayıt ekler.
- Vatandaş sohbetinde sorulan bir hukuki soru, mevzuat bağlamıyla birlikte
  cevaplanır ve kaynak linki gösterir.
- Public `/` sayfası HTTP 200 döner.
