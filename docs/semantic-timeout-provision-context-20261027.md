# Anlam araması ve tam mevzuat bağlamı

Kullanıcı kararı 27 Ekim 2026: önce doğruluk; anlam araması üç saniyede
kesilmesin. Bu turda model üretimi/bulut çağrısı yapılmadı.

## Uygulananlar

- Ortak ANN, mevzuat ANN ve bge-m3 sorgularında işlem-yerel
  `statement_timeout=0`. PostgreSQL genel ayarı değiştirilmedi. Sabit aday
  sayısı, doğrulanmış kaynak/sürüm/tarih filtreleri ve paralellik sınırları
  korunuyor. Bu, bütün korpusu eksiksiz tarama iddiası değildir.
- Genel sohbet kanıt havuzunda cümle ortasında kesilmiş mevzuat için aynı
  kaynağın doğrulanmış kanonik `raw_text` metni okunur. Kaynak kimliği,
  kanun/madde, revision ve source_version eşleşmesi zorunlu. Eski/pending/
  silinmiş kaynak ve özel belge bu yola girmez.
- Kaynak parçası tam metinde aynen bulunmalı (yalnız boşluk normalizasyonu).
  Birden çok madde, yanlış madde veya hâlâ yarım cümle içeren kanonik metin
  kabul edilmez. Yalnız açıkça ayrı sonraki BÖLÜM/KISIM başlığı ayrılır; koşul
  veya istisna taşıyan kuyruk sessizce kesilmez. 16.000 karakterden büyük
  kanonik maddeler bu sınırlı kurtarma yolunda değiştirilmez.
- Veritabanında metin/embedding/index yazısı yok; değişiklik okuma ve kanıt
  hazırlama katmanında. Model, ödeme ve özel veri politikası değişmedi.

## Yerel gerçek veri ölçümleri

| Kontrol | Sonuç |
| --- | --- |
| TBK 315 + Yargıtay sorusu | ortak anlam kolu başarılı, 192 aday, 1,421 sn |
| Konu ifadesiyle aynı ihtar sorusu | ortak anlam kolu başarılı, 192 aday, 0,173 sn |
| Kira arabuluculuğu | ortak anlam kolu başarılı, 192 aday, 0,097 sn |
| 6325 m.18/B | önceden 1798 karakterlik yarım parça kullanılamıyordu; şimdi aynı sürümün 1940 karakterlik tam madde gövdesi kullanılabilir |
| Sahte üretici + gerçek arama | yazıcıya ulaşan 18/B kanıtında kira, dava şartı ve `hariç` istisnası birlikte mevcut |

Süreler bu çalışmanın ölçümleridir; önbellek/disk ısınması etkili olabilir.
Hızlanmayı yalnız timeout değişikliğine bağlamak doğru değildir. Uzun soğuk
arama artık sırf üç saniye doldu diye kesilmeyecek; daha uzun sürebilir.
Kelime aramasının ayrı süreli/tiered geri dönüşü korunuyor; TBK sorusunda bu
kol nedeniyle `partial=true` hâlâ görüldü. Anlam kolu başarılıydı.

## Sınırlar

Bu doğrulama kaynak arama ve yazıcıya ulaşan kanıtı kapsar. Ücretli nihai
cevap/denetçi kalitesinin bütün sorularda düzeldiği anlamına gelmez. Özel
proje/belge sentez yolunda tam madde kurtarma bu değişiklikle etkinleşmez.
Üretim fallback'i ve model ayarları değiştirilmedi. Commit atılmadı.

Son tam çevrimdışı takım: **2613 geçti, 442 atlandı**; ağ bariyeri aktif.
Eski 2/3 saniyelik süreyi bekleyen testler yeni kullanıcı kararına göre
güncellendi; yalnız madde lookup testinin 3 saniyelik beklentisi korundu.
