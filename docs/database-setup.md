# Veritabanı Kurulumu

NHR Legal AI, PostgreSQL 16 ve sabitlenmiş `pgvector 0.8.6` image'ını kullanır. Veritabanı Docker ile çalışır; host portu varsayılan olarak `5433`, container portu `5432`'dir.

## 1. Repoyu ve ortamı hazırla

```powershell
git clone https://github.com/Nurettin-Erdogan/nhr-legal-ai.git
cd nhr-legal-ai
git checkout setup/database-foundation
Copy-Item .env.example .env
```

`.env` içindeki `POSTGRES_PASSWORD` değerini yalnızca kendi bilgisayarında değiştir. `.env` Git'e gönderilmez.

## 2. PostgreSQL'i başlat

Docker Desktop açıkken:

```powershell
docker compose up -d
docker compose ps
```

Beklenen port eşlemesi `localhost:5433 -> container:5432` şeklindedir. Farklı bir host portu gerekiyorsa `.env` içindeki `POSTGRES_PORT` ve `DATABASE_URL` değerlerini birlikte güncelle.

Logları izlemek için:

```powershell
docker compose logs -f db
```

## 3. Bağlantıyı doğrula

```powershell
docker compose exec db psql -U nhr_app -d nhr_legal_ai
```

psql içinde:

```sql
\dt
SELECT extname, extversion
FROM pg_extension
WHERE extname IN ('vector', 'pgcrypto');
```

Çıkış:

```sql
\q
```

### DBeaver

- Host: `localhost`
- Port: `5433`
- Database: `nhr_legal_ai`
- Username: `nhr_app`
- Password: `.env` dosyasındaki `POSTGRES_PASSWORD`

## 4. V2 şeması

Init dosyaları yalnızca boş PostgreSQL volume ilk kez oluşturulurken otomatik çalışır:

1. `database/init/001_extensions.sql`
2. `database/init/002_schema.sql`
3. `database/init/003_v2_schema.sql`
4. `database/init/004_rls.sql`
5. `database/init/005_v2_hardening.sql`
6. `database/init/006_v2_integrity_fixes.sql`

V2 toplam 17 tablo içerir:

- Kimlik ve yetki: `users`, `roles`, `user_roles`
- Hukuk dosyaları: `clients`, `projects`, `project_members`
- Kullanıcı belgeleri: `documents`, `document_chunks`
- Sohbet: `conversations`, `messages`, `citations`
- Hukuk korpusu: `legal_sources`, `legislation_details`, `court_decision_details`, `legal_chunks`
- Kullanıcı özellikleri ve denetim: `saved_legal_sources`, `activity_logs`

`projects` erişimi `project_members.member_role` üzerinden `owner`, `editor` ve `viewer` seviyelerinde yönetilir. Global platform rolleri `roles` ve `user_roles` tablolarındadır.

`legal_sources` ortak kaynak/provenance alanlarını tutar. Mevzuat metadata'sı `legislation_details`, mahkeme ve içtihat metadata'sı `court_decision_details` içindedir. Bir hukuk kaynağı RAG için `legal_chunks` kayıtlarına ayrılır.

`citations` her satırda tam olarak bir `legal_chunk_id` veya `document_chunk_id` taşır. Citation yalnızca `assistant` rolündeki bir mesaja bağlanabilir. Kaynak chunk'ları normal silmede `RESTRICT` ile korunur; fiziksel KVKK purge işleminde önce bağımlı citation kayıtları temizlenmelidir.

## 5. Mevcut V1 veritabanını V2'ye yükselt

Mevcut volume'u silmeden migration dosyalarını sırayla uygula:

```powershell
Get-Content -Raw .\database\init\003_v2_schema.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1

Get-Content -Raw .\database\init\004_rls.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1

Get-Content -Raw .\database\init\005_v2_hardening.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1

Get-Content -Raw .\database\init\006_v2_integrity_fixes.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
```

`003_v2_schema.sql` transaction içinde çalışır. V1 sahiplik ilişkilerini `created_by`, `uploaded_by` ve `project_members` alanlarına taşır. Her citation için önceden belirlenmiş tam bir chunk hedefi ister; keyfî olarak ilk chunk'ı seçmez. Eski hukuk metadata'sı tiplenmiş tablolara ek olarak `metadata.legacy_legal_fields` altında korunur. Veri güvenli biçimde dönüştürülemiyorsa migration rollback yaparak açık hata verir.

`005_v2_hardening.sql`; proje owner bütünlüğünü, hukuk kaynağı subtype bütünlüğünü, kritik sahiplik alanlarını ve citation hedef erişimini koruyan constraint/trigger'ları ekler. Ayrıca RLS altında kullanılacak `nhr_runtime` rolünü `NOLOGIN` olarak hazırlar.

`006_v2_integrity_fixes.sql`; proje oluştururken müvekkil erişimini, owner-only proje soft-delete kuralını, subtype detayının kaynaklar arasında taşınmasını ve eşzamanlı mesaj/citation yazımlarını korur.

Bir migration başarıyla uygulanmış veritabanında aynı migration'ı tekrar çalıştırma. İleride migration runner eklendiğinde dosya sürümleri ayrıca takip edilmelidir.

## 6. Embedding modelini etkinleştir

`document_chunks.embedding` ve `legal_chunks.embedding` model seçilene kadar boyutsuz `VECTOR` kalır. Modelin gerçek çıktı boyutu kesinleştiğinde parametreli migration'ı bir kez çalıştır:

```powershell
$EmbeddingDimensions = 1024 # Bunu seçilen modelin gerçek boyutuyla değiştirin
Get-Content -Raw .\database\migrations\004_configure_embeddings.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai `
    -v ON_ERROR_STOP=1 `
    -v embedding_dimensions=$EmbeddingDimensions
```

Migration:

- Mevcut embedding'lerin seçilen boyutla uyumunu kontrol eder.
- İki kolonu da `VECTOR(n)` tipine geçirir.
- Cosine distance kullanan iki partial HNSW indeksi oluşturur.

`vector` HNSW indeksi en fazla 2000 boyutu desteklediği için migration daha büyük değerleri açık hatayla reddeder.

V2 migration ayrıca iki chunk tablosunda Türkçe full-text `search_vector` kolonlarını ve GIN indekslerini hazırlar. Uygulama katmanı vector ve full-text sonuçlarını birleştirip yeniden sıralayarak hibrit RAG yapabilir.

## 7. RLS ve uygulama kullanıcı bağlamı

Kullanıcıya ait tablolarda Row-Level Security etkindir. Uygulama `nhr_app` ile değil, tablo sahibi olmayan `nhr_runtime` rolüyle bağlanmalıdır.

Yeni veya yükseltilmiş veritabanında runtime şifresini `.env` içine yazdıktan sonra rolün login özelliğini bir kez etkinleştir:

```powershell
$RuntimePassword = (
  Get-Content .env |
  Where-Object { $_ -match '^NHR_RUNTIME_DB_PASSWORD=' }
).Split('=', 2)[1]

Get-Content -Raw .\database\migrations\005_configure_runtime_role.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai `
    -v ON_ERROR_STOP=1 `
    -v runtime_password="$RuntimePassword"

Remove-Variable RuntimePassword
```

Şifreyi komut satırına düz metin olarak yazma. `.env` içindeki `DATABASE_URL`, `nhr_runtime`; `DATABASE_ADMIN_URL` ise yalnız migration işlemleri için `nhr_app` kullanır.

Her uygulama transaction'ı başında doğrulanmış kullanıcı UUID'si yerel ayar olarak verilmelidir:

```sql
BEGIN;
SET LOCAL app.user_id = '00000000-0000-0000-0000-000000000000';
-- Kullanıcı kapsamındaki sorgular
COMMIT;
```

`SET LOCAL` connection pool üzerinde kullanıcı bağlamının sonraki isteğe sızmasını engeller. UUID yalnızca doğrulanmış oturum bilgisinden gelmeli; istemciden gelen ham değer doğrudan kullanılmamalıdır.

Docker'daki `nhr_app` veritabanı sahibidir ve PostgreSQL tablo sahipleri varsayılan olarak RLS'yi bypass eder. Bu hesap yalnız migration ve yerel yönetim içindir. `nhr_runtime` süper kullanıcı değildir, `BYPASSRLS` yetkisi yoktur ve RLS politikalarına tabidir. `FORCE ROW LEVEL SECURITY` ancak migration/operasyon bağlantısı tamamen ayrıldıktan sonra değerlendirilmelidir.

## 8. Güvenlik ve KVKK

- Belge binary'lerini veritabanında değil private object storage'da tut; `documents.storage_key` yalnız referans olsun.
- Object storage erişiminde kısa ömürlü signed URL ve proje üyeliği kontrolü kullan.
- TCKN/VKN gibi kimlik verilerini plaintext veya aranabilir `metadata` içine yazma. `identity_number_ciphertext` uygulama katmanında, anahtarı veritabanından ayrı tutularak doldurulmalıdır.
- `activity_logs.metadata` içine prompt, belge metni, kimlik numarası veya erişim tokenı koyma.
- `deleted_at` normal kullanıcı silmeleri içindir; yasal saklama süresi sona erdiğinde ayrı purge akışı object storage nesnesini, chunk'ları, embedding'leri ve bağımlı citation/chat verisini fiziksel olarak temizlemelidir.
- Yedekleri şifrele, erişimleri en az yetkiyle sınırla ve saklama sürelerini dokümante et.

## 9. Şema testleri

V2 bütünlük, citation ve RLS davranış testleri transaction sonunda rollback yapar:

```powershell
Get-Content -Raw .\database\tests\002_v2_schema_checks.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1

Get-Content -Raw .\database\tests\004_v2_security_checks.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
```

Güvenlik testi; runtime rolüyle proje owner bootstrap, askıya alınmış kullanıcı, kritik alan değişikliği, proje dışı citation, yabancı müvekkil bağlantısı ve subtype kurallarını doğrular.

V1'den veri taşıma testi için boş bir test veritabanında sırasıyla `001_extensions.sql`, `002_schema.sql`, `tests/001_v1_upgrade_fixture.sql`, `003_v2_schema.sql`, `004_rls.sql`, `005_v2_hardening.sql`, `006_v2_integrity_fixes.sql` ve `tests/003_v1_upgrade_assertions.sql` çalıştırılır.

## 10. Veritabanını sıfırlama

Yalnızca tüm yerel veriyi bilerek silmek istediğinde:

```powershell
docker compose down -v
docker compose up -d
```

`docker compose down -v` tüm yerel PostgreSQL verilerini kalıcı olarak siler. Migration uygulamak için bu komutu kullanma.
