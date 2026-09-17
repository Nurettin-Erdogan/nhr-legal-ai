# Mevzuat Aktarımı

Adalet Bakanlığı Bedesten JSON uçlarından (`bedesten.adalet.gov.tr/mevzuat`)
kanun maddelerini toplayıp V2 hukuk tablolarına aktaran ardışık düzen.
Playwright kullanılmaz; portalın kendi JSON arayüzü konuşulur.

Her kanun için Resmî Gazete ve Mevzuat Bilgi Sistemi doğrulaması bir kez
çalışır (madde başına değil). Sonuç kanun numarasıyla bellekte ve, her iki
bayrak da true ise, veritabanında cache'lenir. Bekleyen kanunlar
`python -m worker.runner run --source mevzuat_verify` veya
`scripts/reverify_mevzuat.py` ile ayrı tamamlanır.

## Tasarım

Akış Yargıtay aktarımıyla aynı iki adıma ayrıldı:

1. **Çekme** – Kanun aranır, madde ağacı alınır, her madde diske JSON yazılır.
2. **Aktarım** – JSON arşivi `legal_sources`, `legislation_details` ve
   `legal_chunks` tablolarına yazılır.

RAG birimi kanunun tamamı değil **maddedir**. Asistan `İş Kanunu m. 25`
biçiminde atıf üretebilsin diye her madde ayrı bir `legal_sources` satırıdır.

| Modül | Sorumluluk |
| --- | --- |
| `ingestion/mevzuat/portal.py` | Bedesten JSON uçları, 429/backoff, base64 HTML çözme |
| `ingestion/mevzuat/parser.py` | Tür eşlemesi, madde ağacı düzleştirme, `external_id` |
| `ingestion/mevzuat/fetcher.py` | Arama, madde çekme, hız sınırı |
| `ingestion/mevzuat/archive.py` | Diskteki JSON arşivi |
| `ingestion/mevzuat/store.py` | Veritabanına upsert |

### Tekilleştirme

Doğal anahtar:

```
mevzuat:kanun:4857:m.25
```

Portal `mevzuatId` ve `maddeId` değerleri `metadata` içinde saklanır. Aynı doğal
kimlik ve aynı içerik hash'i tekrar geldiğinde kayıt değişmez. Metin değişmişse
eski satır overwrite edilmez; tarihsel sürüm olarak korunur ve yeni current
sürüm oluşturulur. Güncel sürüm doğal anahtarı veritabanında tekildir.

Portalın güncelleme/yayımlanma tarihi otomatik olarak hukuki yürürlük tarihi
sayılmaz. Doğrulanmış `effective_from` yoksa sistem tarih uydurmaz; bu kayıt
`as_of` tarihli RAG sorgularına dahil edilmez. Ayrıntılar için
[`legal-data-architecture.md`](legal-data-architecture.md) belgesine bakın.

### Tür eşlemesi

| Bedesten `mevzuatTur` | `legislation_details.legislation_type` |
| --- | --- |
| `KANUN` | `law` |
| `KHK`, `CB_KARARNAME` | `decree` |
| `YONETMELIK`, `CB_YONETMELIK`, `KKY`, `UY`, `TUZUK` | `regulation` |
| `TEBLIGLER` | `communique` |
| Kanun no `2709` (Anayasa) | `constitution` |
| diğer | `other` |

## Toplayıcı

Worker tam korpusu sabit kanun listesi olmadan Bedesten `searchDocuments`
keşfiyle çeker (`python -m worker.runner backfill --source all`). Aşağıdaki
`collect --profile starter` komutu yalnız örnek/duman testidir.

```powershell
# Kısa deneme (İş Kanunu 5 madde + 3 karar)
.\.venv\Scripts\python.exe -m ingestion.cli collect --profile smoke --ingest

# Başlangıç korpusu (Anayasa, TMK, TBK, HMK, TCK, CMK, İş, İİK + örnek Yargıtay aramaları)
.\.venv\Scripts\python.exe -m ingestion.cli collect --profile starter --ingest
```

`--only mevzuat` veya `--only yargitay` ile tek kaynak seçilir. Çekim önce
`data/mevzuat` ve `data/yargitay` arşivine yazar; `--ingest` veritabanına aktarır.

Tek kanun veya tek arama için:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli fetch mevzuat --law-no 4857
.\.venv\Scripts\python.exe -m ingestion.cli fetch yargitay --keyword "kıdem tazminatı" --chamber "9. Hukuk Dairesi"
```

## Kullanım

İş Kanunu maddelerini çek (ilk deneme için madde sayısı sınırlı tutulur):

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli fetch mevzuat `
  --law-no 4857 `
  --max-articles 20
```

Aktarım:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli ingest --source mevzuat
```

Aktarım `DATABASE_ADMIN_URL` kullanır. `nhr_runtime` hukuk kaynaklarına yazamaz.

Semantik arama için ardından `python -m ingestion.cli embed` çalıştırılır.

## Testler

Ayrıştırma testleri `tests/fixtures/mevzuat` altındaki canlı yanıtlara dayanır
ve ağ gerektirmez. Veritabanı testleri `NHR_TEST_DATABASE_URL` tanımlıysa
çalışır.

## Bilinen sınırlar

- Resmî uç belgelenmiş genel API sözleşmesi değildir; yanıt değişirse
  `portal.py` ve fixture'lar güncellenir.
- Madde ağacı olmayan türlerde (bazı genelge/karar metinleri) madde üretilemez;
  bu kayıtlar atlanır.
- Üretim taramasında makul hız sınırı (varsayılan 1 sn) ve kullanım şartları
  gözetilmelidir.
