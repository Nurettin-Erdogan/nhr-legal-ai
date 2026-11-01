# Mevzuat veri bütünlüğü — 26 Ekim 2026

> Bu belge onarım **öncesindeki** salt okunur durumun kaydıdır. Uygulanan düzeltmeler, güncel sayılar ve kalan belirsizlikler için [onarım raporuna](legislation-repair-20261026.md) bakın.

## Sonuç

Mevzuat katmanında gerçek madde kimliği ve parçalama sorunları var. Bu tespit, modelin genel cevap kalitesinden bağımsız olarak doğrudan kayıtlar üzerinde yapıldı. Canlı veritabanı salt okunur transaction ile incelendi; kayıt, atıf, sürüm, chunk veya embedding değiştirilmedi. Ücretli model/portal çağrısı yapılmadı. İnceleme mevzuat içindir; milyonlarca mahkeme kararı ve özel kullanıcı belgeleri bu taramaya dahil değildir.

## Sayım

| Ölçüm | Sonuç |
| --- | ---: |
| Silinmemiş mevzuat kaydı, eski sürümler dahil | 87.673 |
| Güncel mevzuat kaydı | 86.527 |
| Güncel ve uygulamanın doğrulanmış kaynak filtresini geçen | 86.490 |
| Güncel tür/kanun-numarası çifti | 5.058 |
| Güncel madde numarası yalnız rakam olmayan kayıt | **0** |
| İlk tanınan madde başlığı ile kayıt numarası uyuşmayan | **16** |
| Aynı kayıt kimliğinin sürümlerinde farklı madde başlıkları bulunan grup | **14** |
| İçinde başka madde başlığı da bulunan güncel kayıt | **2.001 aday** |
| Başlığı mevcut desenle tanınmayan güncel kayıt | **80 aday** |
| Aynı tür/kanun/madde için birden fazla current kayıt | 0 |
| Boş güncel metin veya içerik hash uyuşmazlığı | 0 |

İlk taramadaki 18 başlık uyuşmazlığı, dipnotlu başlıkların (`MADDE 80[1]`) tanınması düzeltilince 16'ya indi. Yukarıdaki nihai değerler bu düzeltmeden sonradır. İlk başlığı uyuşmayan kayıtların tümü mevcut kaynak filtresinden geçiyor; metnin doğrulanmış olması kimliğin doğru olduğunu tek başına garanti etmiyor.

**2.001 ve 80 sayıları otomatik hata sayısı değildir.** Bir değişiklik kanunu başka maddeyi alıntılayabilir; mülga madde aralığı tek paragrafta yer alabilir. Bu adayların resmi belge sınırlarıyla ayrı ayrı karşılaştırılması gerekir. Numara aralıklarındaki boşluklardan otomatik “eksik madde” sonucu çıkarılmadı.

## Doğrudan incelenen örnekler

| Kanun | Veritabanındaki kimlik | Metindeki kimlik | Bulgular |
| --- | --- | --- | --- |
| 6325 | 18 | 18/A | Asıl 18 metni revision 1 ve current=false; ayrı 18/A metni revision 2 ve current=true tutulmuş. Portal madde kimlikleri de farklı. |
| 6100 | 183 | 183/A | Asıl 183 ile ayrı 183/A aynı sürüm zincirine girmiş; 183/A güncel 183 gibi duruyor. |
| 6361 | 39 | 39/A | Güncel kayıt numarası ile madde başlığı uyuşmuyor. |
| 4458 | 35 ve 165 | 35/A ve 165/A | Harfli madde kimlikleri sayısal kimlik altında. |
| 13950 (tebliğ) | 3 | GEÇİCİ 1, sonra MADDE 3 | Tek metinde geçici madde ile asıl madde birleşmiş. |
| 6325 | 36 | 36, ardından GEÇİCİ 1/2/3 | Metin içinde ek/geçici maddeler ayrı kaynak kimliği olmadan duruyor. |

6325 m.18/B doğrudan madde sorgusunda sonuç yok. Bu kanunun incelenen kayıtlarında 18/B için bulunan ifade, 36 altında biriken geçici maddede **18/B'ye yapılan atıf**; bu, 18/B'nin kendi metni değildir. TBK 315 ve 352 ise mevcut, current ve doğrulanmış chunk olarak getirilebiliyor.

## Kod tarafındaki açıklama

1. `ingestion/mevzuat/parser.py::record_from_article` madde kimliğini portalın `maddeNo` alanından alıyor; başlıktaki harf/ek/geçici bilgisiyle karşılaştırmıyor. `article_external_id` de kanun ve bu madde numarasına dayanıyor, farklı `maddeId` tek başına ayrı hukuki kimlik yaratmıyor.
2. `ingestion/mevzuat/store.py::upsert_legislation` aynı tür/kanun/madde kimliği altında farklı metni yeni sürüm sayıyor. Yanlış sayısal kimlik gelince ayrı madde, önceki maddenin yeni sürümü gibi zincirlenebiliyor.
3. `scripts/law_gap_node.py` ve `scripts/ingest_law_gaps.py` boşluk kontrolünde madde numarasının mevcut olmasına bakıyor. Aynı numaraya düşen harfli maddeleri bu yöntem tek başına yakalayamaz.
4. `ingestion/mevzuat/text_verify.py::extract_article_text` için sentetik, ağsız kontrol: yalnız `MADDE 18/A- ...` içeren metinde `article_no='18'` sorgusu 18/A metnini döndürüyor. Sayıdan sonraki `\b`, `/A` ayrımını korumuyor. Bu bir doğrulama belirsizliğidir; her mevcut yanlış kaydın tek sebebi olduğunu kanıtlamaz.

İlk hatanın portal yanıtında mı yoksa daha eski aktarım aşamasında mı doğduğunu kesinleştirmek için resmi madde ağacı/ham belgeyle karşılaştırma gerekir. Şu an kesin olan: mevcut veri bu farklılıkları korumuyor ve kod sınırları bunu engellemiyor.

## Güvenli düzeltme sırası — bu denetimde uygulanmadı

1. Ana madde, harfli madde, ek madde ve geçici madde için ayrık kanonik kimlik; ham portal kimliği ve başlığı korunmalı.
2. Girişte metin başlığı/kimlik uyuşmazlığını reddeden veya incelemeye ayıran kontrol; yanlış kimliği eski maddenin yeni sürümü saymama.
3. Resmi tam metin ve madde ağacıyla karşılaştırmalı kapsam kontrolü; eksik maddeleri kanıtlayarak tamamlama.
4. Önce etkilenen kanunlarda dry-run onarım planı. Mevcut sohbet atıfları, kaynak kimlikleri ve sürüm geçmişi korunmadan toplu UPDATE/DELETE yapılmamalı.
5. Yalnız düzeltilen/eklenen metinlerin chunk ve embeddinglerini yenileme; bütün karar korpusunu yeniden gömmeye gerek olduğu bu taramadan çıkmaz.

## Tekrarlanabilirlik

Salt okunur araç: `scripts/audit_legislation_integrity.py`.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/audit_legislation_integrity.py
```

Makine raporu: `.local/legislation-integrity-20261026.json`. Sınırlı örnekler ve kamuya açık kaynak kimlikleri içerir; özel kullanıcı verisi veya anahtar içermez. Audit ayrıştırıcısının dipnot, harfli, ek ve geçici başlık kontrolleri `tests/test_legislation_integrity_audit.py` içinde; 6/6 test ağ kapalıyken geçti.
