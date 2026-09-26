# RAG kaynak desteği — ilk güvenli adım

Ana sohbet pipeline'ında bir `[K1]` işaretinin varlığı artık tek başına
`grounded=true` üretmez. Cevaptaki her cümle, atıf yaptığı kaynak metnindeki
tam bir cümleyle eşleşmelidir. Boşluk ve çevreleyen alıntı işaretleri
normalleştirilir; sözcük, koşul, sayı ve olumsuzluk değişiklikleri kabul edilmez.
Bir cümlede birden fazla atıf varsa her kaynak aynı cümleyi desteklemelidir.
Başlık/künye, hukuki iddia için metin kanıtı yerine kullanılamaz.

Bu aşama bilinçli olarak **alıntı odaklıdır**: serbest özet ve hukuki yorum
desteklenmez. Kaynak metni verilmeden taslağa sonradan atıf ekleyen ikinci
model çağrısı kaldırılmıştır. Üretim sağlayıcısı değişmez; aynı kontrol tüm
sağlayıcılara uygulanır.

## Gösterme ve kayıt

- Yeni cevaplar, gösterim/sohbet kaydı/cevap önbelleğinden önce kontrol edilir.
- Eski önbellek cevapları da güncel kaynak metinleriyle yeniden kontrol edilir.
  Başarısız olan cevap servis edilmez; yeni üretim aynı kontrolden geçer.
- Desteksiz cevap HTTP 422 olur; ilerleme akışında cevap metni yayınlanmaz.
- Kaynak yetersizliği durumunda yalnız sabit yetersizlik mesajı gösterilir.
- Metin eşleşmesi `third_party` kaynağı resmî kaynağa dönüştürmez. Portal
  doğrulaması ile cevabın kaynak desteği birbirinden ayrı kontrollerdir.

## Sınırlar

Bu bir anlamsal doğruluk veya hukuki uygunluk garantisi değildir. Kaynaktan
aynen alınmış bir cümle de soruya ilgisiz, tarihsel veya daha geniş bağlamda
istisnaya tabi olabilir. Cümle ayrıştırma ihtiyatlıdır; kısaltma, OCR hatası ve
chunk sınırları doğru alıntıların reddedilmesine yol açabilir. Sonlandırılmamış
kaynak kuyruğu kabul edilmez. Chunk başındaki bağlam kaybı hâlâ bir sınırlamadır.

Bu değişiklik ayrı `office_ai` modüllerini, belge üretme akışlarını, arayüzdeki
demo verileri veya retrieval hızını düzeltmez. Bunlar sonraki adımlardır.
Semantik özetleri açmadan önce, sabit bir soru/kaynak değerlendirme setinde
destek, çelişki, istisna, tarihsel sürüm ve kaynak ilgililiği ölçülmelidir.

## Test

`tests/test_source_support.py` ve `tests/test_source_support_pipeline.py`;
ters hukuki sonuç, olumsuzluk değişimi, koşul çıkarma, ek iddia, yanlış/eksik
atıf, önbellek atlatması ve üçüncü taraf rozetinin korunmasını kapsar.
Pipeline testleri model/DB/portal ve embedding işçisi yan etkilerini taklit eder;
gerçek model başarı oranı veya canlı portal doğrulama sonucu değildir.
