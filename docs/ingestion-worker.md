# NHR Legal Data Collector / Ingestion Worker

Web uygulamasından bağımsız çalışan hukuk veri toplama servisi. Tarayıcı
açık tutulmaz; masaüstü scraper yoktur. `ingestion/yargitay`,
`ingestion/danistay`, `ingestion/mevzuat`, `ingestion/kdk` ve
`ingestion/aym` HTTP istemcileri worker; Resmî Gazete ve Mevzuat Bilgi
Sistemi istemcileri doğrulama katmanı
tarafından orkestre edilir.

## Mimari

```
Source adapters → scheduler / CLI → fetch → raw snapshot (data/, gitignore)
  → validate → deduplicate → change detection → PostgreSQL
  → chunk → embedding backfill (ayrı komut) → RAG
```

Worker hata verse bile FastAPI ve Next.js ayakta kalır. Korpus yazımı
`DATABASE_ADMIN_URL` (`nhr_app`) ile yapılır; uygulama `nhr_runtime` kullanır.

## Kaynak listesi

| Durum | Kaynak | Resmi adres | Transport |
| --- | --- | --- | --- |
| **ACTIVE** | Yargıtay | https://karararama.yargitay.gov.tr | JSON/HTTP: `/detayliArama`, `/aramadetaylist`, `/getDokuman?id=` |
| **ACTIVE** | Danıştay | https://karararama.danistay.gov.tr | Oturumlu JSON/HTTP: `/detayliArama`, `/aramadetaylist`, `/getDokuman?id=` |
| **ACTIVE** | Mevzuat | https://bedesten.adalet.gov.tr/mevzuat | JSON/HTTP: `searchDocuments`, `mevzuatMaddeTree`, `getDocumentContent` |
| **ACTIVE** | AYM | https://kararlarbilgibankasi.anayasa.gov.tr | Public arama JSON'u + public UDF karar dosyası |
| **ACTIVE / VERIFICATION** | Resmî Gazete | https://www.resmigazete.gov.tr | Mevzuat sync içinde `/Home/Filter` + resmî arşiv künye teyidi |
| **ACTIVE / VERIFICATION** | Mevzuat Bilgi Sistemi | https://www.mevzuat.gov.tr | Mevzuat sync içinde resmî `/anasayfa/MevzuatDatatable` araması + detay sayfasındaki konsolide PDF/DOC teyidi |
| ACTIVE | KDK | https://kararlar.ombudsman.gov.tr | Public DataTables JSON künyesi + resmî karar PDF'i |

## Scheduler

Celery yok. `python -m worker.runner daemon` süreç açıkken due checkpoint'leri
çalıştırır. Aralıklar `.env` ile değişir; varsayılanlar resmi portalları
yoracak kadar sık değildir.

| Değişken | Varsayılan | Anlam |
| --- | --- | --- |
| `YARGITAY_SYNC_INTERVAL_MINUTES` | 360 | Yargıtay turları arası |
| `DANISTAY_SYNC_INTERVAL_MINUTES` | 720 | Danıştay turları arası |
| `MEVZUAT_SYNC_INTERVAL_MINUTES` | 720 | Mevzuat turları arası |
| `KDK_SYNC_INTERVAL_MINUTES` | 1440 | KDK turları arası |
| `AYM_SYNC_INTERVAL_MINUTES` | 1440 | AYM turları arası |
| `YARGITAY_BACKFILL_INTERVAL_MINUTES` | 60 | Eksik Yargıtay penceresinde başarılı turlar arası |
| `DANISTAY_BACKFILL_INTERVAL_MINUTES` | 90 | Eksik Danıştay penceresinde başarılı turlar arası |
| `MEVZUAT_BACKFILL_INTERVAL_MINUTES` | 120 | Eksik mevzuat keşif kataloğunda başarılı turlar arası |
| `KDK_BACKFILL_INTERVAL_MINUTES` | 180 | Eksik KDK penceresinde başarılı turlar arası |
| `AYM_BACKFILL_INTERVAL_MINUTES` | 180 | Eksik AYM sayfalarında başarılı turlar arası |
| `WORKER_POLL_SECONDS` | 30 | Daemon beklerken kontrol sıklığı |
| `YARGITAY_DELAY_SECONDS` | 1.5 | İstek arası bekleme |
| `DANISTAY_DELAY_SECONDS` | 2.0 | Danıştay istekleri arası bekleme |
| `MEVZUAT_DELAY_SECONDS` | 1.0 | İstek arası bekleme |
| `KDK_DELAY_SECONDS` | 2.0 | KDK istekleri arası bekleme |
| `AYM_DELAY_SECONDS` | 2.0 | AYM kayıtları arası bekleme |
| `YARGITAY_MAX_RECORDS_PER_RUN` | 80 | Bir turda en fazla karar |
| `DANISTAY_MAX_RECORDS_PER_RUN` | 50 | Bir turda en fazla Danıştay kararı |
| `MEVZUAT_MAX_ARTICLES_PER_RUN` | 50 | Bir turda en fazla madde |
| `KDK_MAX_RECORDS_PER_RUN` | 40 | Bir turda en fazla KDK kararı |
| `AYM_MAX_RECORDS_PER_RUN` | 40 | Bir turda en fazla AYM kararı |
| `YARGITAY_CORPUS_START` | 2000-01-01 | Yargıtay: boş kelime+yıl 2000'de hit, 1995 SUCCESS 0 |
| `DANISTAY_CORPUS_START` | 1982-01-01 | Danıştay: 1981 SUCCESS 0, 1982 hit |
| `KDK_CORPUS_START` | 2017-01-01 | KDK IndexPaging tarih filtresi 2017 hit, 2016 SUCCESS 0 |
| `CURRENT_LOOKBACK_DAYS` | 45 | Güncel şeridin taradığı son gün sayısı |
| `CURRENT_SYNC_INTERVAL_MINUTES` | 180 | Güncel şerit lookback turunu bitirip ufuğa sarıldıktan sonra |
| `CURRENT_RETRY_INTERVAL_MINUTES` | 60 | Güncel şerit ayı bitirmediyse veya lookback içinde sonraki aya geçiyorsa |
| `FULL_CORPUS_START` | 2000-01-01 | Yalnız AYM gibi tarih penceresi olmayan kaynaklarda yedek; kaynak tabanı ezmez |
| `BACKFILL_PAUSE_SECONDS` | 2 | Full backfill turları arası kısa bekleme |
| `DANISTAY_BACKFILL_PAUSE_SECONDS` | 30 | Danıştay'da başarılı ay turları arası asgari bekleme; boş ayların 429 üretmesini önlemeye yardımcı olur |
| `MEVZUAT_DISCOVERY_TYPES` | KANUN,KHK,... | Bedesten keşif türleri |
| `EMBED_LIMIT_PER_RUN` | 200 | Her sync sonrası en fazla yeni chunk embedding |

`python -m worker.runner backfill --source all` tarihsel korpusu checkpoint ile
doldurur. `--source all` varsayılan olarak her ACTIVE kaynağı ayrı süreçte
çalıştırır (aynı portala iki süreç yok). Tek süreç için `--serial`.
`--serial` modunda da hatalı/kısmi veya ilerlemeyen kaynak, kendi normal
`next_run_at` aralığına kadar ertelenir; bu sırada diğer kaynaklar taranır.
Resmî portal HTTP 429 döndürürse aynı isteğe kısa aralıkla tekrar yüklenilmez.
CAPTCHA görülen kaynak otomatik aşılmaz ve bloklu olarak raporlanır.
Yargıtay/Danıştay/KDK aylık pencereler kaynak `*_CORPUS_START` değerinden
(doğrulanmış en eski hit; boş SUCCESS yıllar complete yazılmaz ancak
taranabilir). Eski checkpoint 2020 gibi daha yeni bir yıldaysa ve eski
ayların tarandığı kanıtlanamıyorsa, `horizon_audit_version` geçişi imleci
bir kez resmî başlangıç tarihine geri alır; kayıtlar silinmez, tekrarlar
tekilleştirilir. Yargıtay tam tarama tarih penceresi + boş `arananKelime`
kullanır; tarihsiz boş kelime resmi portalde ERROR verir, varsayılan `"karar"`
filtresi kullanılmaz. Pencere ancak
`expected = seen = stored+duplicate+quarantined` ve `failed=0` iken
complete olur. AYM `kararTipi` değerleri resmi search 422 listesidir:
BireyselBasvuru, NormDenetimi, SiyasiParti, YuceDivan, YasamaDokunulmazligi;
her tür ayrı partition. CAPTCHA bypass yoktur. Raw yanıtlar `data/raw/<kaynak>/raw`
altında URL, SHA256, fetched_at ile saklanır.
mevcut rate-limit ve `*_MAX_*` tavanları korunur; süreç kesilirse aynı komut
kaldığı yerden devam eder. Her başarılı turdan sonra `legal_chunks` içindeki
yeni parçalar embed edilir. Kaynak tarihsel olarak bitince incremental
`daemon` moduna geçer (güncel şerit + periyodik tarama). CAPTCHA olan kaynak
atlanır, bypass yoktur.

İlk daemon turu `next_run_at` boşsa işi due sayar. Yargıtay, Danıştay ve KDK
iki şeritte yürür: `backfill` arşivi doldurur, `current` son
`CURRENT_LOOKBACK_DAYS` içindeki takvim aylarını yeniden tarar. Daemon her
kaynakta önce current, sonra backfill çalıştırır. Aynı resmi portal için
advisory lock kanonik kaynak adındadır; iki şerit paralel vurmaz.
Checkpoint'ler ayrıdır (`yargitay` / `yargitay:current`). Coverage kanonik
kaynağa yazılır; current şerit `complete=true` yazmaz, çünkü içinde
bulunduğumuz ay kapanmış sayılmaz.

Başarılı turdan sonra tamamlanmamış tarih/sayfa penceresi veya geçmişte kalan
sonraki pencere varsa backfill aralığı kullanılır. Hata, kısmi başarı veya
CAPTCHA sonrasında normal uzun aralık korunur; portalı sıkıştırmak için
otomatik retry yapılmaz. Backfill tamamlandığında normal periyodik aralık
devreye girer. Mevcut `next_run_at` kayıtları geriye dönük değiştirilmez; yeni
aralık, sonraki başarılı turda uygulanır.
Karantinaya alınan kayıt dışında hata yoksa ve imleç gerçekten ilerlediyse
`partial` tur kısa backfill aralığıyla devam eder. İlerlemeyen, başarısız veya
CAPTCHA isteyen tur yine uzun beklemeye alınır; karantina kaydı korunur ve
eksik pencere tamamlanmış sayılmaz.

## Checkpoint / resume

Tablo: `source_sync_checkpoints`.

Yargıtay ve Danıştay cursor: tarih penceresi (`window_from` / `window_to`), sayfa,
sayfa içi `row_offset`, `last_external_id`, `window_complete`,
`next_window_start`. Yargıtay `pageSize=20` değerini turlar arasında sabit
tutar; tur sayfanın ortasında biterse sonraki satırdan devam eder. Eski,
`row_offset` içermeyen Yargıtay checkpoint'leri kayıt atlamamak için aynı
pencerenin ilk sayfasından tekrar başlar; mevcut kayıtlar kimlikle
tekilleştirilir. Hatalı/karantinaya düşen satır penceresini tamamlanmış
saydırmaz ve sonraki turda yeniden denenir.

KDK cursor: tarih penceresi, DataTables `offset`, `window_complete` ve
`next_window_start`.

AYM cursor: global sonuç sırasındaki `page` ve sayfa içi `row_offset`.

Mevzuat cursor: `mode=discovery`, `type_index`, `catalog_page`,
`catalog_offset`, `law_no`, `last_article_no`. Bedesten kataloğu kanun/KHK/
yönetmelik türlerinde sayfalanır; sabit starter liste worker'da kullanılmaz.
Madde limiti bir metnin ortasında biterse aynı `law_no` üzerinden devam eder.
`law_no` içermeyen eski starter cursor keşfe geçer; mevcut maddeler hash ile
tekilleştirilir. `--law-no` ile tek metin aktarımı keşif imlecini değiştirmez.

Süreç CTRL+C ile durursa run `cancelled`/`partial` olur; checkpoint son güvenli
pencere/sayfada kalır. Yeniden başlatma `--no-resume` yoksa kaldığı yerden devam eder.

## Job kayıtları ve kilit

`source_sync_runs` her turu sayaçlarla tutar (`queued`/`running`/`success`/
`partial`/`failed`/`cancelled`/`captcha_required`).

Aynı kanonik kaynak için PostgreSQL advisory lock (`pg_try_advisory_lock`).
Backfill ve current aynı portal kilidini paylaşır. Yargıtay, Danıştay,
mevzuat, KDK ve AYM birbirini bloklamaz.

## Retry / backoff / CAPTCHA

- 429: `Retry-After` + üstel backoff + jitter, sonra retry
- 5xx: backoff + retry
- 401/403: retry yok; iş fail
- CAPTCHA: bypass yok; run `captcha_required`, health `blocked`
- Playwright birincil yöntem değildir

## Versioning ve change detection

`content_hash` karşılaştırması:

| Sonuç | Yargıtay / Danıştay / KDK | Mevzuat |
| --- | --- | --- |
| created | yeni `external_id` (`yargitay:<id>` / `danistay:<id>` / `kdk:<id>`) | yeni madde |
| unchanged | aynı hash; atıflı chunk'lara dokunulmaz | aynı hash |
| updated | atıfsız karar yerinde revision | — |
| new_version | atıflı karar: eski `is_current=false`, yeni current satır | içerik değişince yeni historical satır; eski `effective_to` kapanır |

Atıflı chunk'lar sessiz silinmez. Sahte esas/karar no üretilmez; portal JSON
birinci kaynaktır.

## Provenance

`legal_sources` üzerinde canonical / official URL, ingestion_method, fetched_at,
content_hash, source_version, is_current. Transport (Bedesten) ile hukuki kanon
(Resmî Gazete) ayrı tutulur. Resmî Gazete doğrulama alanları
(`official_gazette_*`, `verified_against_gazette`) mevzuat metadata'sında durur.
Gazete tarih/sayı/mevzuat numarası resmî arşivde eşleşirse arşiv URL'si ve
doğrulama zamanıyla birlikte `verified_against_gazette=true` yazılır. Bu teyit,
yayın tarihini kendiliğinden yürürlük tarihi yapmaz.

Mevzuat Bilgi Sistemi doğrulaması aynı sync içinde kanun numarası, başlık ve
Resmî Gazete künyesini karşılaştırır. Arama sonucundaki resmî detay sayfasında
tekil konsolide PDF/DOC bağlantısı bulunmadan `verified_against_mbs=true`
yazılmaz. Sonuç ve URL'ler `mbs_verification`, `mbs_url` ve `mbs_pdf_url`
metadata alanlarında saklanır. MBS metni ikinci bir mevzuat korpusu olarak
yazılmaz; böylece Bedesten maddeleriyle mükerrer kaynak oluşmaz.

Eksik kritik alanlar `legal_source_quarantine` kuyruğuna düşer, `legal_sources`'a
yazılmaz.

Ham yanıtlar `data/raw/` altına gider; Git'e girmez.

## Yargıtay ve Danıştay karar korpusu

Aylık pencereler. Backfill şeridinde tamamlanan pencere
`source_coverage_windows.complete=true`. Daemon her turda kaynağa ait limitle
bir pencereyi işler. Güncel şerit aynı ayları lookback ufku içinde yeniden
tarar ve ay bitince ufuğun başına döner. Danıştay detaylı arama transportu
serbest kelime filtresi sunmadığı için tarih ve isteğe bağlı daire filtresi
kullanılır.

## KDK karar korpusu

KDK mahkeme olmadığı için kararlar `source_type=other` olarak saklanır. Karar
numarası, tarihi, türü, şikâyet numarası, konu ve şikâyet edilen kurum
`metadata` içinde korunur. Tam metin yalnız resmî PDF'den çıkarılır; karar
künyesi portalın yapılandırılmış JSON alanlarından alınır.

## AYM karar korpusu

AYM bireysel başvuru künyesi public arama JSON'undan alınır. Tam metin,
public karar-dosyaları listesinin gösterdiği UDF attachment içindeki
`content.xml` dosyasından çıkarılır. UDF'deki başvuru numarası JSON künyesiyle
eşleşmeden kayıt korpusa alınmaz. Bireysel başvurularda olmayan bir karar
numarası üretilmez; `docket_no` başvuru numarasıdır ve kullanıcıya `B. No:`
olarak gösterilir. Güvenlik doğrulaması isteyen PDF üretim ucu kullanılmaz.

## Embedding

`python -m worker.runner backfill` her başarılı turdan sonra `legal_chunks`
içinde vektörü olmayan parçaları embed eder. Embedding düşse hukuk satırı
kalır; sonraki tur yeniden dener. Elle: `python -m ingestion.cli embed --target legal`.

## Monitoring API

Yalnız `admin` rolü:

- `GET /api/admin/ingestion/status`
- `GET /api/admin/ingestion/coverage`
- `GET /api/admin/ingestion/runs`
- `GET /api/admin/ingestion/sources`
- `POST /api/admin/ingestion/run/{source}` — daemon kuyruğu (`next_run_at=now`)
- `POST /api/admin/ingestion/run/{source}?lane=current` — güncel şerit kuyruğu

Frontend admin paneli bu sprintte yok.

## Manuel komutlar

```powershell
.\.venv\Scripts\python.exe -m worker.runner backfill --source all
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay --lane current
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay --date-from 2026-01-01 --date-to 2026-01-31
.\.venv\Scripts\python.exe -m worker.runner run --source danistay --date-from 2025-01-01 --date-to 2025-01-31
.\.venv\Scripts\python.exe -m worker.runner run --source mevzuat
.\.venv\Scripts\python.exe -m worker.runner run --source mevzuat --law-no 1475 --max-records 10
.\.venv\Scripts\python.exe -m worker.runner run --source kdk --date-from 2026-09-01 --date-to 2026-09-30 --max-records 10
.\.venv\Scripts\python.exe -m worker.runner run --source aym --max-records 10
.\.venv\Scripts\python.exe -m worker.runner run --source aym --keyword "2024/31235" --max-records 1 --no-resume
.\.venv\Scripts\python.exe -m worker.runner run --source all --dry-run
.\.venv\Scripts\python.exe -m worker.runner status
.\.venv\Scripts\python.exe -m worker.runner daemon
.\.venv\Scripts\python.exe -m ingestion.cli worker run --source yargitay
```

`--law-no` ile tek kanun aktarımı starter mevzuat checkpoint'ini ve sonraki
zamanlanmış turu değiştirmez; her çağrıda ilgili kanunu baştan tarar ve aynı
maddeleri içerik kimliğiyle tekilleştirir. 1475 sayılı kanun starter kataloğuna
sona eklenmiştir; mevcut `law_index` değerleri korunur.

Migration (mevcut volume):

```powershell
Get-Content -Raw .\database\migrations\006_legal_data_layer.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\007_ingestion_worker.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\008_current_source_integrity.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\009_kdk_source_checkpoint.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\010_activate_danistay_source.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\011_activate_resmi_gazete_verification.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\012_activate_kdk_source.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
Get-Content -Raw .\database\migrations\013_activate_aym_source.sql |
  docker compose exec -T db psql -U nhr_app -d nhr_legal_ai -v ON_ERROR_STOP=1
```

## Bilinen sınırlar

- AYM PDF üretim ucu güvenlik doğrulaması ister; worker bu ucu kullanmaz ve
  yalnız açık public UDF attachment akışıyla çalışır.
- Yargıtay ve Danıştay CAPTCHA sonrası insan müdahalesi gerekir.
- Portal `recordsFiltered` her daire/anahtar kelime aramasına bağlıdır; "tüm Yargıtay 2020–2026" tek bir sayı değildir. Coverage pencereleri anahtar kelime `karar` ile taranır; daire bazlı taramayı CLI `--chamber` ile verin.
- Büyük korpus Git'te tutulmaz.
- Embedding kota hataları ingestion'ı geri almaz; backfill tekrarlanır.
