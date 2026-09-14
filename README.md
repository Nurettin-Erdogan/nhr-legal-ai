# nhr-legal-ai

Hukuki araştırma, doküman analizi ve kaynak gösterimli yapay zekâ soru-cevap süreçleri için geliştirilen hukuk asistanı platformu.

## Veritabanı

Proje PostgreSQL 16, pgvector ve Docker Compose kullanır. Yerel veritabanı varsayılan olarak `localhost:5433` adresinde çalışır.

Kurulum, V2 migration, RLS, embedding indeksleri ve test adımları için [veritabanı kurulum dokümanına](docs/database-setup.md) bakın.

## Veri aktarımı

Yargıtay kararları `ingestion` paketiyle toplanır ve hukuk tablolarına aktarılır. Ayrıntılar için [Yargıtay karar aktarımı dokümanına](docs/ingestion-yargitay.md) bakın.

## Web uygulaması

PostgreSQL çalışırken API'yi proje kökünde başlatın:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8765
```

Başka bir PowerShell penceresinde frontend'i başlatın:

```powershell
cd web
npm install
npm run dev
```

Uygulama `http://localhost:3000`, API dokümantasyonu
`http://localhost:8765/docs` adresinde açılır. Frontend farklı bir API adresi
kullanacaksa `web/.env.local.example` dosyasını `.env.local` adıyla kopyalayıp
değeri değiştirin.

## Gemini kaynaklı cevaplar

AI asistanını etkinleştirmek için Google AI Studio'dan alınan anahtarı yalnızca
yerel `.env` dosyasına ekleyin:

```env
AI_PROVIDER=gemini
AI_MODEL=gemini-3.8-flash
GEMINI_API_KEY=buraya_kendi_anahtariniz
RAG_TOP_K=6
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSIONS=768
```

API'yi yeniden başlattıktan sonra `http://localhost:3000/assistant` adresindeki
ekran etkinleşir. Asistan önce PostgreSQL tam metin indeksinden ilgili karar
parçalarını seçer, ardından bu parçaları sabit `[K1]`, `[K2]` kaynak işaretleriyle
Gemini'ye gönderir. API anahtarı frontend'e aktarılmaz.

### Semantik arama

Embedding depolamasını 768 boyut için bir kez yapılandırın:

```powershell
$EmbeddingDimensions = 768
Get-Content -Raw .\database\migrations\004_configure_embeddings.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai `
    -v embedding_dimensions=$EmbeddingDimensions
```

Ardından mevcut hukuk parçalarının vektörlerini üretin:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli embed --batch-size 10
```

Embedding bulunan korpuslarda RAG, Türkçe tam metin ve cosine benzerlik
sonuçlarını reciprocal-rank fusion ile birleştirir. Embedding servisi geçici
olarak kullanılamazsa mevcut tam metin aramasıyla çalışmaya devam eder.

## Kullanıcı hesabı

Kayıt ve giriş ekranı `http://localhost:3000/auth` adresindedir. Parolalar
Argon2 ile hash'lenir; süreli JWT hem API yanıtında hem de `HttpOnly`, `SameSite=Lax`
cookie olarak verilir. Yerel `.env` dosyasına en az 32 karakterlik rastgele bir
imzalama sırrı ekleyin:

```env
JWT_SECRET=buraya_uzun_rastgele_bir_deger
JWT_EXPIRE_MINUTES=480
AUTH_COOKIE_SECURE=false
ALLOW_REGISTRATION=true
```

Production ortamında `AUTH_COOKIE_SECURE=true` kullanılmalı ve uygulama HTTPS
üzerinden sunulmalıdır. Yeni hesaplara başlangıçta `lawyer` rolü atanır; sonraki
proje ve belge işlemleri runtime bağlantısında kullanıcı kimliğini PostgreSQL
RLS oturumuna aktarabilir.

## Proje ve dava dosyaları

`http://localhost:3000/projects` ekranı oturum kullanıcısının erişebildiği dava,
icra, danışmanlık ve araştırma projelerini listeler. Yeni proje oluşturulurken
kullanıcı `owner` üye olarak eklenir. API, JWT içindeki kullanıcı kimliğini
transaction boyunca `app.user_id` PostgreSQL ayarına aktarır; proje ve belge
görünürlüğünü mevcut RLS politikaları sınırlar.
