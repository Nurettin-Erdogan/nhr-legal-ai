# Yargıtay Karar Aktarımı

Yargıtay karar arama portalından karar toplayıp V2 hukuk tablolarına aktaran
ardışık düzen. İlk prototip (`jsonscraper.py`) bu modüle taşındı.

## Tasarım

Akış bilinçli olarak iki adıma ayrıldı:

1. **Tarama** – Portal taranır, kararlar diske JSON olarak yazılır.
2. **Aktarım** – JSON arşivi `legal_sources`, `court_decision_details` ve
   `legal_chunks` tablolarına yazılır.

Arşiv ara katman olduğu için aktarım mantığı değiştiğinde portalın yeniden
taranması gerekmez; tarama pahalı ve hız sınırlıdır.

| Modül | Sorumluluk |
| --- | --- |
| `ingestion/yargitay/portal.py` | Resmî JSON uçları, oturum, CAPTCHA/hata tespiti ve HTML temizleme |
| `ingestion/yargitay/parser.py` | Eski/düz metin girdileri için yedek künye ayrıştırma |
| `ingestion/yargitay/chunking.py` | Karar metnini RAG parçalarına bölme |
| `ingestion/yargitay/archive.py` | Diskteki JSON arşivi ve tekilleştirme indeksi |
| `ingestion/yargitay/scraper.py` | Arama sayfalama, hız sınırlama ve normalize karar üretimi |
| `ingestion/yargitay/store.py` | Veritabanına upsert |
| `ingestion/cli.py` | Komut satırı arayüzü |

### Tekilleştirme

Güncel portal kayıtlarında resmî `id` alanından bir `external_id` üretilir:

```
yargitay:1224329000
```

Bu değer hem arşiv indeksinin hem de `legal_sources (source_type, external_id)`
tekil indeksinin anahtarıdır. `daire`, `esasNo`, `kararNo` ve `kararTarihi`
arama yanıtının yapılandırılmış alanlarından alınır; karar gövdesindeki benzer
numaralar künye sanılmaz. Eski arşivlerin bileşik kimlikleri okunmaya devam eder.

### Ayrıştırma

Portalın güncel arayüzünde kullanılan akış şudur:

1. `GET /` ile oturum açılır.
2. `POST /detayliArama` ile arama bağlamı kurulur.
3. `POST /aramadetaylist` ile yapılandırılmış karar listesi alınır.
4. `GET /getDokuman?id=...` ile tam karar HTML'i alınır ve düz metne çevrilir.

Bu yaklaşım ekrandaki CSS sınıflarına bağlı değildir. `parser.py` eski/düz metin
girdileri için ağ bağımlılığı olmayan yedek ayrıştırıcıdır. Hem
etiketli (`ESAS NO : 2019/1234`) hem de son ekli (`2019/1234 E.`) biçimler
desteklenir.

Türkçe `İ/I` harfleri Python'un varsayılan küçültmesiyle beklendiği gibi
eşlenmediğinden desenler `tr_casefold` ile katlanmış metne uygulanır.

Karar gövdesindeki etiketsiz tarihler çoğunlukla olay tarihi olduğu için
yalnızca etiketli tarihler karar tarihi sayılır; liste başlıkları tek tarih
içerdiğinden orada etiketsiz tarihe izin verilir.

### Parçalama ve embedding

`legal_chunks` satırları paragraf sınırları korunarak üretilir; ilk aktarımda
`embedding` alanı boş bırakılır. Depolama
`database/migrations/004_configure_embeddings.sql` ile modelin boyutuna göre
yapılandırılır. Ardından `python -m ingestion.cli embed` komutu eksik veya model
adı değişmiş vektörleri geri doldurur. İşlem kesilirse daha önce tamamlanan
parçalar korunur ve sonraki çalıştırma kaldığı yerden devam eder.

Toplu embedding varsayılan olarak batch'ler arasında 7 saniye bekler. Geçici
429/5xx hatalarında üstel beklemeyle yeniden dener; `--delay`, `--max-retries`
ve `--retry-backoff` değerleri gerektiğinde değiştirilebilir. Her başarılı
batch ayrı transaction olarak kalıcılaştırılır; sonraki bir hata daha önce
üretilmiş vektörleri geri almaz.

RAG katmanı embedding bulunan parçalarda cosine benzerliği ile Türkçe tam metin
sonuçlarını reciprocal-rank fusion ile birleştirir. Embedding servisi
kullanılamadığında tam metin araması çalışmaya devam eder.

Karar metni değişmediyse parçalar yeniden üretilmez; böylece o parçalara
verilmiş atıflar korunur.

## Kurulum

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Kullanım

Tarama:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli scrape `
  --keyword "kıdem tazminatı" `
  --chamber "9. Hukuk Dairesi" `
  --decision-date-from 2025-01-01 `
  --decision-date-to 2025-12-31 `
  --max-decisions 50
```

İstekler arası beklemeyi `--delay`, liste sayfa boyutunu `--page-size` ile
değiştirebilirsiniz. `--refresh-existing` arşivde bulunan kararların metnini
yeniden kontrol eder. Arşiv varsayılan olarak `data/yargitay` altına yazılır ve
`.gitignore` kapsamındadır.

Büyük korpus aktarımlarını yıl veya daha kısa tarih dilimlerine ayırın. Portal
429 ya da geçici 5xx döndürürse istemci `Retry-After` başlığını gözetir ve her
denemede bekleme süresini üstel artırır.

Aktarım:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli ingest
```

Aktarım `DATABASE_ADMIN_URL` bağlantısını kullanır. Korpus yazımı yönetimsel
bir iştir; `nhr_runtime` rolü RLS nedeniyle hukuk kaynaklarına yazamaz.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Ayrıştırma ve parçalama testleri bağımlılıksız çalışır. Veritabanı testleri
yalnızca `NHR_TEST_DATABASE_URL` tanımlıysa çalışır ve yazdıklarını geri alır:

```powershell
$env:NHR_TEST_DATABASE_URL = "postgresql://nhr_app:SIFRE@localhost:5433/nhr_legal_ai_test"
.\.venv\Scripts\python.exe -m pytest tests -q
```

`nhr_legal_ai_test` ayrı ve şeması kurulmuş bir test veritabanı olmalıdır.
Canlı `nhr_legal_ai` veya `DATABASE_ADMIN_URL` test URL'si olarak kullanılmaz.

## Bilinen sınırlar

- Portal CAPTCHA istediğinde süreç bunu aşmaya çalışmaz ve açık hatayla durur.
- Resmî uçlar belgelenmiş genel API sözleşmesi değildir; yanıt sözleşmesi
  değişirse `portal.py` adaptörü ve sözleşme testleri güncellenmelidir.
- Üretim taramasında resmî sitelerin kullanım şartları, makul hız sınırı ve
  yeniden kullanım koşulları gözetilmelidir. Varsayılan bekleme 1.5 saniyedir.
- Mevcut korpusta semantik aramanın devreye girmesi için API anahtarıyla
  `ingestion.cli embed` geri doldurma komutunun ayrıca çalıştırılması gerekir.
