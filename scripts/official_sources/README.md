# NHR Legal AI — 7 resmî kaynak

Bu klasör yalnızca kaynakları proje ağacında **tek tek görünür** kılan giriş dosyalarını içerir. Üretim toplama mantığı `ingestion/` ve `worker/` içinde kalır; aynı scraper kodu ikinci kez kopyalanmaz.

| # | Kaynak | Resmî adres | Rol | Üretim kodu |
|---|---|---|---|---|
| 1 | Yargıtay | https://karararama.yargitay.gov.tr | Korpusa karar/tam metin | `ingestion/yargitay`, `worker/adapters/yargitay.py` |
| 2 | Danıştay | https://karararama.danistay.gov.tr | Korpusa karar/tam metin | `ingestion/danistay`, `worker/adapters/danistay.py` |
| 3 | AYM | https://kararlarbilgibankasi.anayasa.gov.tr | Korpusa karar/tam metin | `ingestion/aym`, `worker/adapters/aym.py` |
| 4 | KDK | https://kararlar.ombudsman.gov.tr | Korpusa idari karar/tam metin | `ingestion/kdk`, `worker/adapters/kdk.py` |
| 5 | Bedesten / Mevzuat | https://bedesten.adalet.gov.tr/mevzuat/ | Korpusa mevzuat maddeleri | `ingestion/mevzuat`, `worker/adapters/mevzuat.py` |
| 6 | Resmî Gazete | https://www.resmigazete.gov.tr | Mevzuat künyesi doğrulama | `ingestion/resmi_gazete` |
| 7 | Mevzuat Bilgi Sistemi | https://www.mevzuat.gov.tr | Künye + konsolide PDF/DOC doğrulama | `ingestion/mevzuat_bilgi_sistemi` |

İlk beş kaynak gerçek corpus ingestion kaynağıdır. Son iki kaynak aynı mevzuatı tekrar DB'ye yazmaz; Bedesten kaydını bağımsız resmî kaynaklarla çapraz doğrular.

Örnek:

```powershell
.\.venv\Scripts\python.exe scripts\official_sources\01_yargitay.py
.\.venv\Scripts\python.exe scripts\official_sources\02_danistay.py
.\.venv\Scripts\python.exe scripts\official_sources\03_aym.py
.\.venv\Scripts\python.exe scripts\official_sources\04_kdk.py
.\.venv\Scripts\python.exe scripts\official_sources\05_mevzuat_bedesten.py
.\.venv\Scripts\python.exe scripts\official_sources\06_resmi_gazete.py
.\.venv\Scripts\python.exe scripts\official_sources\07_mevzuat_bilgi_sistemi.py
```

`DATABASE_ADMIN_URL` yerel `.env` içinde tanımlı olmalıdır. Kaynak başına üretim rate-limit/backoff/checkpoint kuralları worker tarafından uygulanır.
