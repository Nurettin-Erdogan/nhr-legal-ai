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
| `ingestion/yargitay/parser.py` | Metinden esas no, karar no, tarih ve daire çıkarımı |
| `ingestion/yargitay/chunking.py` | Karar metnini RAG parçalarına bölme |
| `ingestion/yargitay/archive.py` | Diskteki JSON arşivi ve tekilleştirme indeksi |
| `ingestion/yargitay/scraper.py` | Playwright ile portal tarama, retry ve hız sınırlama |
| `ingestion/yargitay/store.py` | Veritabanına upsert |
| `ingestion/cli.py` | Komut satırı arayüzü |

### Tekilleştirme

Her karar için mahkeme, daire, esas ve karar numarasından türetilen bir
`external_id` üretilir:

```
yargitay/9-hukuk-dairesi/2019-1234/2021-5678
```

Bu değer hem arşiv indeksinin hem de `legal_sources (source_type, external_id)`
tekil indeksinin anahtarıdır; aynı karar tekrar tarandığında yeni satır
oluşmaz. Esas veya karar numarası okunamayan kayıtlar tekilleştirilemeyeceği
için atlanır ve loglanır.

### Ayrıştırma

`parser.py` yalnızca düz metinle çalışır, ağ veya tarayıcı bağımlılığı yoktur;
bu nedenle portal HTML'i değişse bile testleri geçerliliğini korur. Hem
etiketli (`ESAS NO : 2019/1234`) hem de son ekli (`2019/1234 E.`) biçimler
desteklenir.

Türkçe `İ/I` harfleri Python'un varsayılan küçültmesiyle beklendiği gibi
eşlenmediğinden desenler `tr_casefold` ile katlanmış metne uygulanır.

Karar gövdesindeki etiketsiz tarihler çoğunlukla olay tarihi olduğu için
yalnızca etiketli tarihler karar tarihi sayılır; liste başlıkları tek tarih
içerdiğinden orada etiketsiz tarihe izin verilir.

### Parçalama ve embedding

`legal_chunks` satırları paragraf sınırları korunarak üretilir; `embedding`
alanı boş bırakılır. Embedding modeli seçildikten sonra
`database/migrations/004_configure_embeddings.sql` çalıştırılıp vektörler geri
doldurulmalıdır.

Karar metni değişmediyse parçalar yeniden üretilmez; böylece o parçalara
verilmiş atıflar korunur.

## Kurulum

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Kullanım

Tarama:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli scrape `
  --keyword "kıdem tazminatı" `
  --chamber "9. Hukuk Dairesi" `
  --max-decisions 50
```

Portalın DOM yapısını izlemek için `--headed`, istekler arası beklemeyi
değiştirmek için `--delay` kullanılır. Arşiv varsayılan olarak `data/yargitay`
altına yazılır ve `.gitignore` kapsamındadır.

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
$env:NHR_TEST_DATABASE_URL = $env:DATABASE_ADMIN_URL
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Bilinen sınırlar

- `ScraperConfig` içindeki CSS seçicileri ilk prototipten devralındı ve canlı
  portala karşı doğrulanmadı. İlk çalıştırma `--headed` ile yapılıp seçiciler
  gerekirse güncellenmelidir.
- Portalın kullanım koşulları ve `robots.txt` kuralları üretim taramasından
  önce gözden geçirilmelidir; varsayılan 1.5 saniyelik bekleme koruyucu bir
  alt sınırdır.
- Kararlar yalnızca `legal_chunks` düzeyinde saklanır; embedding üretimi ve
  arama katmanı henüz bağlı değildir.
