# nhr-legal-ai

Hukuki araştırma, doküman analizi ve kaynak gösterimli yapay zekâ soru-cevap süreçleri için geliştirilen hukuk asistanı platformu.

## Dosya düzeni

Kod, yerel veri ve geçici çalışmaların yerleri için [klasör rehberine](docs/file-structure.md) bakın.

## Veritabanı

Proje PostgreSQL 16, pgvector ve Docker Compose kullanır. Yerel veritabanı varsayılan olarak `localhost:5433` adresinde çalışır.

Kurulum, V2 migration, RLS, embedding indeksleri ve test adımları için [veritabanı kurulum dokümanına](docs/database-setup.md) bakın.

## Veri aktarımı

Yargıtay/Danıştay kararları ve mevzuat maddeleri `ingestion` paketi ve `worker`
servisiyle toplanır. Worker, web uygulamasından bağımsız çalışır.
Mevzuat künyeleri ayrıca T.C. Resmî Gazete arşiviyle otomatik çapraz
doğrulanır; doğrulama kanıtı kaynak metadata'sında saklanır.

```powershell
.\.venv\Scripts\python.exe -m worker.runner backfill --source all
.\.venv\Scripts\python.exe -m worker.runner status
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay --lane current
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay --date-from 2026-01-01 --date-to 2026-01-31
.\.venv\Scripts\python.exe -m worker.runner run --source danistay --date-from 2025-01-01 --date-to 2025-01-31
.\.venv\Scripts\python.exe -m worker.runner daemon
```

`backfill --source all` her kaynağı ayrı süreçte çeker; aynı resmi portala
iki süreç bağlanmaz. Delay, CAPTCHA bypass ve metinsiz kayıt yoktur. 429 ve
CAPTCHA süreci durdurmaz; sırasıyla ~15 sn ve ~30 sn soğuma sonrası
aynı imleçten yeniden dener. `--source all` her kaynağı ayrı süreçte tutar;
çocuk süreç çıkarsa parent yeniden başlatır.
Tarihsel taban kaynak bazlıdır (Yargıtay 2000, Danıştay 1982, KDK 2017);
taranmayan dönem complete yazılmaz. Azure 1 GB için `--serial --no-embed`.

Eski tek seferlik toplayıcı hâlâ durur:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli collect --profile smoke --ingest
```

Kaynak/provenance ve versiyonlama kuralları için
[NHR Legal Data Layer](docs/legal-data-architecture.md); operasyon ayrıntıları için
[ingestion worker](docs/ingestion-worker.md),
[Yargıtay](docs/ingestion-yargitay.md) ve
[mevzuat](docs/ingestion-mevzuat.md) dokümanlarına bakın.

## Web uygulaması

PostgreSQL çalışırken API'yi proje kökünde başlatın:

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8765
```

Başka bir PowerShell penceresinde frontend'i başlatın:

```powershell
cd web
npm ci
npm run dev -- --port 3000
```

Uygulama `http://localhost:3000`, API dokümantasyonu
`http://localhost:8765/docs` adresinde açılır. Frontend farklı bir API adresi
kullanacaksa `web/.env.local.example` dosyasını `.env.local` adıyla kopyalayıp
değeri değiştirin.

## Qwen kaynaklı cevaplar (yerel Ollama)

Ollama'yı yerel makinede başlatın ve sohbet ile embedding modellerini yükleyin:

```powershell
ollama pull qwen3.5:4b
ollama pull nomic-embed-text
```

Proje kökündeki `.env` dosyasında sohbet için Qwen'i seçin. Mevcut korpusun
768 boyutlu `nomic-embed-text` vektörleri korunur; sohbet modelini değiştirmek
embedding modelini veya veritabanındaki vektörleri değiştirmez.

```env
AI_PROVIDER=qwen
AI_MODEL=qwen3.5:4b
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_TIMEOUT_SECONDS=180
OLLAMA_MAX_OUTPUT_TOKENS=768
OLLAMA_NUM_CTX=4096
OLLAMA_KEEP_ALIVE=30m
RAG_TOP_K=6
RAG_CONTEXT_CHARS=2400
RAG_QUERY_EMBEDDING=true
RAG_EXPLANATIONS=true
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
```

API'yi yeniden başlattıktan sonra `http://localhost:3000/dashboard/ai` adresindeki
ekran etkinleşir. Asistan önce korpusta ilgili mevzuat ve karar parçalarını
seçer, ardından bu parçaları sabit `[K1]`, `[K2]` kaynak işaretleriyle
Qwen'e gönderir. API, cevaptaki atıf işaretlerinin gerçekten getirilen
kaynaklara karşılık geldiğini doğrular; hukuki iddiaların maddi doğruluğunu
otomatik olarak kanıtlamaz. Yerel Ollama için API anahtarı gerekmez; servisi kimlik doğrulamasız
internete açmayın. Ollama geçici olarak çalışmazsa embedding yerine sözcüksel
arama devam eder, fakat model yanıtı üretilemez.
Yerel geçiş ve karşılaştırmalı ölçüm ayrıntıları: [RAG iyileştirmesi](docs/rag-upgrade.md).
DeepSeek silinmedi: geri dönüş için `AI_PROVIDER=deepseek` ve
`AI_MODEL=deepseek-r1:8b` seçip API'yi yeniden başlatın.
`RAG_EXPLANATIONS=false` yalnız tam kaynak alıntılarına döner. Açıklama modu,
atıf/sayı kontrolleri ve ayrı destek/kapsam değerlendirmesi kullanır; doğruluk
garantisi değildir. Uzun numaralı koşul listeleri eksik özetlenmez, aynen korunur.

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

Google ile giriş kurulumu, mevcut hesabı güvenli bağlama ve üretim ayarları:
[docs/google-login.md](docs/google-login.md). Google Calendar ayrı bir entegrasyondur.

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

Yeni TanStack/Vite arayüzünün kurulum ve ekran sınırları için
[frontend kurulumu](web/README.md) ve [geçiş raporu](docs/frontend-transition.md).
Büro ekranlarındaki `office_*` kayıtları aşağıdaki RAG proje/belge API'lerinden
ayrıdır; büroya yüklenen belge otomatik olarak RAG'e indekslenmiş sayılmaz.

Eski RAG proje API'si oturum kullanıcısının erişebildiği dava,
icra, danışmanlık ve araştırma projelerini listeler. Yeni proje oluşturulurken
kullanıcı `owner` üye olarak eklenir. API, JWT içindeki kullanıcı kimliğini
transaction boyunca `app.user_id` PostgreSQL ayarına aktarır; proje ve belge
görünürlüğünü mevcut RLS politikaları sınırlar.

## Kullanıcı belgeleri

Eski RAG belge API'sinde PDF, DOCX ve UTF-8 TXT belgeleri
yüklenebilir. Dosyalar varsayılan olarak `uploads/` altında kullanıcı kimliğiyle
ayrılmış özel dizinlere kaydedilir; bu dizin Git'e eklenmez. Belge metni yükleme
sırasında parçalanarak `document_chunks` tablosuna yazılır. Listeleme ve ekleme
işlemleri `nhr_runtime` bağlantısı ve PostgreSQL RLS politikalarıyla korunur.

Boyut ve saklama yolu `.env` içinden ayarlanabilir:

```env
DOCUMENT_STORAGE_DIR=uploads
MAX_DOCUMENT_SIZE_MB=10
```

Taranmış veya yalnız görüntü içeren PDF'ler henüz OCR'dan geçirilmez; API bu
dosyaları boş belge olarak kaydetmek yerine açık bir hata döndürür.

AI asistanında bir proje seçildiğinde merkezi mevzuat/karar korpusu ile yalnız
o projedeki erişilebilir belge parçaları birlikte sıralanır. Kullanıcı belgesi
atıfları dosya adı, sayfa ve bölüm bilgisiyle gösterilir; konuşma kaydındaki
atıf doğrudan ilgili `document_chunk_id` değerine bağlanır.

Özel belge parçalarının semantik aranması için embedding aktarımı ayrıca ve
açıkça başlatılır. Bu işlem belge metnini yapılandırılan embedding sağlayıcısına
gönderdiğinden KVKK/veri işleme şartları doğrulandıktan sonra çalıştırılmalıdır:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli embed --target documents --batch-size 10
```

`--target legal` varsayılandır; `--target all` iki kaynağı sırayla işler.
