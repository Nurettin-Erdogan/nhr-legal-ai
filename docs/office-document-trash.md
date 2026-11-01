# Dava belgeleri: çöp kutusu ve kalıcı silme

Belge silme iki adımlıdır: **önce çöp kutusuna taşınır** (geri alınabilir), **sonra kalıcı silinir**. Bu,
yanlışlıkla silmeyi geri alınabilir yapar; kalıcı silme ise müvekkil verisi için gerçek bir silmedir
(KVKK, avukatlık sırrı).

## Davranış

| İşlem | Ne olur |
| --- | --- |
| **Çöpe taşı** | `office_case_documents.deleted_at` işaretlenir. Belge dosya listelerinden, aramadan (dava sohbeti), indekslemeden, belge durumundan ve yineleme denetiminden çıkar. Türetilmiş metne dokunulmaz. |
| **Geri yükle** | `deleted_at` temizlenir. Anlıktır, belge yeniden indekslenmez, aramaya hemen döner. |
| **Kalıcı sil** | Yalnız çöpteki belge için (iki adım şart). Aşağıya bakın. |
| **Otomatik** | Çöpteki belge `OFFICE_TRASH_RETENTION_DAYS` (varsayılan **30**) gün sonra kendiliğinden kalıcı silinir (API içinde 6 saatte bir çalışan döngü). |

## Kalıcı silme neleri siler

1. **Belgeye dayanan sohbet cevapları temizlenir.** Cevap metni belgeden aynen alıntı içerebilir
   (kaynak-destek denetimi birebir cümle ister); bu yüzden o cevapların metni yer tutucuyla değiştirilir
   (`messages.metadata.redacted = "source_deleted"`) ve atıf kayıtları (`citations`, bunlar belgeden
   özet de taşır) silinir. Soru metni kalır.
2. Belge satırı silinir; türetilmiş `documents` ve `document_chunks` (metin, embedding) `ON DELETE CASCADE`
   ile birlikte gider.
3. Diskteki dosya kaldırılır.
4. Bellekteki cevap önbelleği temizlenir (silinen belgeden alıntı taşıyabilir).
5. Denetim kaydına `office.case_document_delete_forever` yazılır (dosya adı ve içerik yazılmaz, yalnız
   temizlenen cevap sayısı).

Eskiden `citations.document_chunk_id` `ON DELETE RESTRICT` olduğundan, sohbette atıf yapılmış belge
**hiç silinemiyordu** (genel tablo ucundan silme "kullanımda" hatası veriyordu). Bu sorun çözüldü.

## Uçlar (`api/office_trash.py`)

| Uç | Açıklama |
| --- | --- |
| `GET /api/office/documents/trash?case_id=` | Çöpteki belgeler: `days_left`, `cited_answers` (kalıcı silinirse kaldırılacak cevap sayısı). |
| `POST /api/office/documents/{id}/trash` | Çöpe taşı. Olmayan, başkasının ve zaten çöpteki belge 404 (ayırt edilmez). |
| `POST /api/office/documents/{id}/restore` | Geri yükle. |
| `DELETE /api/office/documents/{id}` | Kalıcı sil. Çöpte değilse **409**; yanıtta `redacted_answers`. |

Genel tablo ucu (`/api/office/case_documents`) bunları atlayamaz: çöpteki satırları görmez ve değiştiremez,
`deleted_at` istemciden yazılamaz (ne `insert` ne `update`), `delete` **409** verir.

## Arayüz

- **Dosyalar** sayfası: çöp simgesi belgeyi çöpe taşır ("Geri al" eylemli bildirim), altta **Çöp kutusu**.
- **Dava → Evraklar**: her evrakta "Çöpe taşı", altta o davanın çöp kutusu.
- Çöp kutusu: kalan gün, o belgeye dayanan cevap sayısı, **Geri yükle** ve **Kalıcı sil**. Kalıcı silme
  onayı geri alınamayacağını ve kaç cevabın kaldırılacağını açıkça söyler.

## Bilinen sınırlar

- Silinen belgeden **başka yerlere** kopyalanan metin silinmez: büro yapay zekâ çıktıları
  (`office_ai_outputs`), kullanıcının belgeden kopyaladığı not/dilekçe ve eklentinin kullanıcı
  bilgisayarına bıraktığı yerel kopya (`İndirilenler/NHR-Hukuk-UYAP`, yalnız "yerel kopya" açıksa).
- Yedekler (veritabanı/disk yedeği) silinmez; saklama politikası yedekler için ayrıca belirlenmelidir.
- "Çöp kutusunu boşalt" (toplu kalıcı silme) yoktur; belgeler tek tek silinir.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_document_trash.py -q   # NHR_TEST_DATABASE_URL gerekir
```

Testler gerçek RLS'li veritabanında şunları doğrular: çöpteki belgenin aramadan/listeden/yinelemeden
çıkması, geri yükleme, kalıcı silmenin cevapları ve atıfları temizlemesi ve başka kullanıcıya
dokunmaması, süresi dolanın toplanması, genel ucun atlanamaması ve HTTP akışı. Korumalar tek tek
kaldırılarak testlerin başarısız olduğu doğrulanmıştır.
