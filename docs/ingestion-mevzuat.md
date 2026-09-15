# Mevzuat Aktarımı

Adalet Bakanlığı Bedesten JSON uçlarından (`bedesten.adalet.gov.tr/mevzuat`)
kanun maddelerini toplayıp V2 hukuk tablolarına aktaran ardışık düzen.
Playwright kullanılmaz; portalın kendi JSON arayüzü konuşulur.

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

Portal `mevzuatId` ve `maddeId` değerleri `metadata` içinde saklanır; kanun veya
madde numarası değişmeden portal kimliği değişirse aynı satır güncellenir.

### Tür eşlemesi

| Bedesten `mevzuatTur` | `legislation_details.legislation_type` |
| --- | --- |
| `KANUN` | `law` |
| `KHK`, `CB_KARARNAME` | `decree` |
| `YONETMELIK`, `CB_YONETMELIK`, `KKY`, `UY`, `TUZUK` | `regulation` |
| `TEBLIGLER` | `communique` |
| Kanun no `2709` (Anayasa) | `constitution` |
| diğer | `other` |

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
