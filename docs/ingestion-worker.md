# NHR Legal Data Collector / Ingestion Worker

Web uygulamasından bağımsız çalışan hukuk veri toplama servisi. Tarayıcı
açık tutulmaz; masaüstü scraper yoktur. `ingestion/yargitay`,
`ingestion/danistay`, `ingestion/mevzuat` ve `ingestion/kdk` HTTP istemcileri worker
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
| PLANNED / VERIFICATION | AYM | https://kararlarbilgibankasi.anayasa.gov.tr | Public arama JSON'u doğrulandı; tam metin güvenlik doğrulaması bekliyor |
| **ACTIVE / VERIFICATION** | Resmî Gazete | https://www.resmigazete.gov.tr | Mevzuat sync içinde `/Home/Filter` + resmî arşiv künye teyidi |
| ACTIVE | KDK | https://kararlar.ombudsman.gov.tr | Public DataTables JSON künyesi + resmî karar PDF'i |
| PLANNED | Mevzuat canonical | resmi mevzuat sistemi / Resmî Gazete | Bedesten transport kaynağıdır, hukuki kanon değildir |

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
| `WORKER_POLL_SECONDS` | 30 | Daemon beklerken kontrol sıklığı |
| `YARGITAY_DELAY_SECONDS` | 1.5 | İstek arası bekleme |
| `DANISTAY_DELAY_SECONDS` | 2.0 | Danıştay istekleri arası bekleme |
| `MEVZUAT_DELAY_SECONDS` | 1.0 | İstek arası bekleme |
| `KDK_DELAY_SECONDS` | 2.0 | KDK istekleri arası bekleme |
| `YARGITAY_MAX_RECORDS_PER_RUN` | 40 | Bir turda en fazla karar |
| `DANISTAY_MAX_RECORDS_PER_RUN` | 30 | Bir turda en fazla Danıştay kararı |
| `MEVZUAT_MAX_ARTICLES_PER_RUN` | 30 | Bir turda en fazla madde |
| `KDK_MAX_RECORDS_PER_RUN` | 20 | Bir turda en fazla KDK kararı |
| `YARGITAY_CORPUS_START` | 2020-01-01 | Tam korpus için ilk ay penceresi |
| `DANISTAY_CORPUS_START` | 2020-01-01 | Danıştay için ilk ay penceresi |
| `KDK_CORPUS_START` | 2020-01-01 | KDK için ilk ay penceresi |

İlk daemon turu `next_run_at` boşsa kaynağı due sayar; sonraki turlar
interval kadar bekler.

## Checkpoint / resume

Tablo: `source_sync_checkpoints`.

Yargıtay ve Danıştay cursor: tarih penceresi (`window_from` / `window_to`), sayfa,
`last_external_id`, `window_complete`, `next_window_start`.

KDK cursor: tarih penceresi, DataTables `offset`, `window_complete` ve
`next_window_start`.

Mevzuat cursor: `law_index`, `last_article_no`.

Süreç CTRL+C ile durursa run `cancelled`/`partial` olur; checkpoint son güvenli
pencere/sayfada kalır. Yeniden başlatma `--no-resume` yoksa kaldığı yerden devam eder.

## Job kayıtları ve kilit

`source_sync_runs` her turu sayaçlarla tutar (`queued`/`running`/`success`/
`partial`/`failed`/`cancelled`/`captcha_required`).

Aynı kaynak için PostgreSQL advisory lock (`pg_try_advisory_lock`). Yargıtay,
Danıştay, mevzuat ve KDK birbirini bloklamaz.

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

Eksik kritik alanlar `legal_source_quarantine` kuyruğuna düşer, `legal_sources`'a
yazılmaz.

Ham yanıtlar `data/raw/` altına gider; Git'e girmez.

## Yargıtay ve Danıştay karar korpusu

Aylık pencereler. Tamamlanan pencere `source_coverage_windows.complete=true`.
Daemon her turda kaynağa ait limitle bir pencereyi işler. Danıştay detaylı
arama transportu serbest kelime filtresi sunmadığı için tarih ve isteğe bağlı
daire filtresi kullanılır.

## KDK karar korpusu

KDK mahkeme olmadığı için kararlar `source_type=other` olarak saklanır. Karar
numarası, tarihi, türü, şikâyet numarası, konu ve şikâyet edilen kurum
`metadata` içinde korunur. Tam metin yalnız resmî PDF'den çıkarılır; karar
künyesi portalın yapılandırılmış JSON alanlarından alınır.

## Embedding

Fetch sırasında Gemini çağrılmaz. `python -m ingestion.cli embed --target legal`
ayrı backfill'dir. Embedding düşse hukuk satırı kalır.

## Monitoring API

Yalnız `admin` rolü:

- `GET /api/admin/ingestion/status`
- `GET /api/admin/ingestion/runs`
- `GET /api/admin/ingestion/sources`
- `POST /api/admin/ingestion/run/{source}` — daemon kuyruğu (`next_run_at=now`)

Frontend admin paneli bu sprintte yok.

## Manuel komutlar

```powershell
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay
.\.venv\Scripts\python.exe -m worker.runner run --source yargitay --date-from 2026-01-01 --date-to 2026-01-31
.\.venv\Scripts\python.exe -m worker.runner run --source danistay --date-from 2025-01-01 --date-to 2025-01-31
.\.venv\Scripts\python.exe -m worker.runner run --source mevzuat
.\.venv\Scripts\python.exe -m worker.runner run --source kdk --date-from 2026-09-01 --date-to 2026-09-30 --max-records 10
.\.venv\Scripts\python.exe -m worker.runner run --source all --dry-run
.\.venv\Scripts\python.exe -m worker.runner status
.\.venv\Scripts\python.exe -m worker.runner daemon
.\.venv\Scripts\python.exe -m ingestion.cli worker run --source yargitay
```

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
```

## Bilinen sınırlar

- AYM public arama JSON'u doğrulandı ancak tam karar
  indirme güvenlik doğrulaması otomatik aşılmaz.
- Yargıtay ve Danıştay CAPTCHA sonrası insan müdahalesi gerekir.
- Portal `recordsFiltered` her daire/anahtar kelime aramasına bağlıdır; "tüm Yargıtay 2020–2026" tek bir sayı değildir. Coverage pencereleri anahtar kelime `karar` ile taranır; daire bazlı taramayı CLI `--chamber` ile verin.
- Büyük korpus Git'te tutulmaz.
- Embedding kota hataları ingestion'ı geri almaz; backfill tekrarlanır.
