# Kamu veri doğrulama denetimi — 27 Ekim 2026

**Tam veri doğruluğu onayı verilmedi.** Bu tur salt okunur denetimdir; veri,
kimlik, durum, atıf, parça, embedding veya resmîlik bayrağı değiştirilmedi.
Ücretli model çağrısı yapılmadı. Özel kullanıcı tabloları taranmadı.

## Kapsam

1. Silinmemiş mevzuatın tamamında yerel kimlik/hash/bütünlük denetimi.
2. Bütün kamu kaynaklarında kaynak türü/durum/yöntem ve provenance alanlarının
   tam envanteri (26,29 saniye). Bu, bütün metinlerin hash'inin yeniden
   hesaplanması veya resmî portaldan tekrar indirilmesi değildir.
3. Altı kanunun resmî MBS PDF'si birer kez indirilerek **1323 güncel madde**
   karşılaştırıldı: 6325, 6098, 4857, 6361, 4458, 1512. İlk farkların nedenini
   ayırmak için 6325 ve 4857 üzerinde ayrıca kısa fark incelemesi yapıldı.

## Tam mevzuat yerel taraması

| Ölçüm | Sonuç |
| --- | ---: |
| Silinmemiş kayıt, tarihsel sürümler dahil | 87674 |
| Güncel kayıt | 86532 |
| Güncel, görünür kayıt | 86492 |
| Tür/kanun numarası çifti | 5058 |
| Boş metin / içerik hash uyuşmazlığı / çift güncel kimlik | 0 / 0 / 0 |
| İlk başlığı kayıt kimliğiyle uyuşmayan güncel kayıt | 11 |
| Başlık deseni tanınmayan kayıt | 80 inceleme adayı |
| İçinde başka madde başlığı bulunan kayıt | 2001 inceleme adayı |
| Farklı başlıklar taşıyan sürüm zinciri | 10 inceleme adayı |

11 uyuşmazlık önceki onarımdan kalanlardır; yeni ortaya çıkmış 11 hata diye
sunulamaz. Bunların arasında 6361 m.39 → 39/A, 4458 m.35 → 35/A ve m.165 →
165/A, 1512 m.71 → 71/A var. Bütün sürüm zinciri ve resmî tarih incelenmeden
otomatik taşıma/silme yapılmadı. 2001/80 sayıları doğrulanmış hata sayısı değildir.

## Bütün kamu kaynaklarının metadata envanteri

- Ready mahkeme kararı: **11169699**. Bu gruplarda eksik kaynak URL'si veya
  eksik hash alanı yok; kayıtlı `verify_status=mismatch` yok.
- Pending bulk karar: **47731**; uygulamaya açılmadı. 46516'sında URL eksik.
- Diğer ready kamu kaynakları: **93389** (KDK, Rekabet, Sayıştay, Uyuşmazlık).
- Bedesten ready mevzuat: 86534 tarihsel+güncel kayıt; portal eşleşme bayrağı
  var. Ayrı MBS madde-metni karşılaştırma bayrağı bulunan yalnız bir kayıt.
  Ayrıca ayrı resmî PDF aktarımı olan bir kayıtta madde-metni kanıtı var.

Bu son sayı kayıtlı belirli alanlara aittir; başka yöntemle yapılmış doğrulamayı
yok saymaz. Ancak mevcut `ready`/portal bayrağı tek başına her **madde metninin**
birebir karşılaştırıldığını kanıtlamıyor. Kanun kimliği doğrulaması ile madde
metni doğrulaması raporlarda ve sonraki aktarım kapısında ayrılmalı.

## Resmî PDF karşılaştırması

| Kanun | Güncel kayıt | Yalnız boşluklar yok sayılınca birebir eşleşen |
| --- | ---: | ---: |
| 6325 | 40 | 1 |
| 6098 | 649 | 466 |
| 4857 | 122 | 2 |
| 6361 | 54 | 0 |
| 4458 | 248 | 58 |
| 1512 | 210 | 0 |
| Toplam | 1323 | 527 |

Geri kalanlar: 777 metin farkı inceleme adayı, 7 tekrarlanan PDF başlığı,
11 PDF ayrıştırıcısının başlığını bulamadığı kayıt, 1 biçim normalizasyonu adayı.
**Bunlar 796 yanlış hüküm anlamına gelmez.** PDF paragraf sınırları, üst/alt
başlık, dipnot ve sürüm farkları ayrı değerlendirilmelidir.

Doğrudan bakılan 6325 m.1 ve m.10 ile 4857 m.1 ve m.10 örneklerinde farklılıklar
önceki/sonraki madde başlıkları ve değişiklik dipnotlarında görüldü. Bu,
karşılaştırıcıda paragraf/madde sınırı normalizasyonunun şart olduğunu gösterir;
diğer adayların da aynı nedenle farklı olduğu varsayılmaz. Eşleşmeyen kayıtlar
otomatik silinmedi veya resmîlikten çıkarılmadı.

## Sonraki güvenli çalışma

1. Kesin kimlik uyuşmazlıkları: resmî madde ağacı/PDF ve sürüm zincirine bağlı
   yedekli onarım planı; eski atıflar korunmalı.
2. Madde gövdesi, sonraki başlık ve editoryal dipnotu ayrı ayrıştırıp exact
   karşılaştırmayı yeniden yapmak. Sayı/olumsuzluk/istisna farklarını asla
   benzerlik oranıyla kabul etmemek.
3. Kalan hüküm farklarını sürüm tarihi ve resmî metinle incelemek. Ancak bundan
   sonra düzeltilecek veya incelemeye ayrılacak kayıt listesi kesinleşebilir.
4. Kararların tam içerik/künye denetimi ayrı aşama: mevcut envanter, milyonlarca
   kararı yeniden portaldan doğrulamanın yerine geçmez. Portal hız/CAPTCHA
   kuralları korunmalı; toplu doğrulama kontrollü ve kaldığı yerden sürmeli.

Araçlar: `scripts/audit_legislation_integrity.py` (audit fonksiyonu),
`scripts/audit_public_corpus_metadata.py`, `scripts/audit_official_legislation_text.py`.
Son iki araç varsayılan olarak veritabanına yazamaz; read-only transaction kullanır.
