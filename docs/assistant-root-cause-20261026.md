# Normal sohbet: arama ve tekrar maliyeti — 2026-10-26

Bu kontrol sırasında ücretli model çağrısı yapılmadı. Kaynak okumaları salt
okunur; embedding işçileri/Docker/PostgreSQL bakımı yapılmadı.

## Yeniden üretilen hata

Gerçek veritabanında `TÜFE nedir?` sorusu için:

- Önce metin araması sıfır aday döndürüyordu. Kısa, çekimden arındırılmış
  kelimeler 4 karakter sınırına takılabiliyor; kısaltmanın açılımı sorguda yoktu.
- Vektör sonuçları içinden kalan mevzuat adayları 2521 m.9/m.10 tüfek
  hükümleriydi: pasaj eşleşmesi `tüfe` sözcüğünü `tüfek` içinde buluyordu.
- Model bu nedenle soruya uygun olmayan kanıtlar alabiliyordu. Bu durum
  embedding sayısını artırmakla veya yalnız model değiştirmekle giderilmez.
- Doğal cevap önbelleği kodda açıkça kapalıydı. Ayrıca kısa bağımsız sorular
  geçmiş üzerinden yeniden yorumlanabiliyordu; aynı soru fazladan üretime gidebiliyordu.
- Hata günlüğü doğal cevap yolunun gerçek nedeni yerine kullanılmayan sentez
  sözlüğünü (`{}`) yazıyordu; eldeki günlüklerden geçmiş denetçi gerekçeleri çıkarılamıyor.

## Uygulanan düzeltmeler

- Ortak, tam sözcük sınırına bağlı sorgu sözlüğü: kısaltma açılımları metin
  araması, sorgu embedding'i ve pasaj seçimi için aynı biçimde kullanılır.
  Bu açılımlar **cevap kanıtı değildir**; cevap yine gerçek kaynak metnine dayanır.
- Tanım sorularında kaynaktaki açık kavram/kısaltma ilişkisi, ilgisiz kullanım
  örneklerinden önce sıralanır. Yazıcıdan tanımın dışındaki ödeme/tarife örneklerini
  sırf kaynakta geçiyor diye anlatmaması istenir.
- Bağımsız kavram tanımlarında önceki konu içeriği taşınmaz; sohbet sahipliği
  yine kontrol edilir. `Bu nedir?`, kişisel olgu ve belge soruları bu yola girmez.
- Yalnız daha önce denetlenmiş doğal cevap nesnesi, kullanıcı/model/soru/kanıt
  anahtarıyla yeniden kullanılabilir. Atıfların güncel sorgu sonucunda bulunması,
  güvenilirliği, metni, sürümü ve künyesi yeniden kontrol edilir. Kaynak değişirse
  isabet geçersizdir. Düz metin veya başarısız cevap kanıt sayılmaz.
- Doğal yolun hata kodu, deneme/cümle sayısı ve eleme türü günlüğe yazılır;
  soru, taslak, kaynak gövdesi, anahtar veya özel bilgiler yazılmaz.

## Doğrulama ve sınır

- Düzeltmeden sonra embedding/model olmadan metin araması yaklaşık 0,33 sn'de
  tamamlandı; ilk sonuç 11297 m.3, 2007/1 sayılı değişken faizli konut finansmanı
  tebliğiydi. Metin `Tüketici Fiyat Endeksi (TÜFE)` ve açıklayan kurumu içeriyor.
- Kaydedilmiş kamuya açık metin ve sahte model yanıtlarıyla tanımın mekanik
  denetimden geçmesi, tüfek metninin elenmesi, önbellek isabeti, kaynak değişimi,
  kullanıcı izolasyonu ve geçmişten konu taşımama otomatik testlere bağlandı.
- Bu testler gerçek sağlayıcının her seferinde doğru yazacağını garanti etmez.
  Kredi harcamamak için bu turda yeni canlı üretim testi yapılmadı. Geniş korpus
  sorgularının zaman aşımı ihtimali de tamamen giderilmiş değildir.

Commit yok; diğer çalışma ağacı değişiklikleri korundu. Derin araştırma modeli
ve özel belge akışının politikası değiştirilmedi.
