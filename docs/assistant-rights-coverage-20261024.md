# Asistan: genel haklar sorusunda eksik kapsam — 2026-10-24

## Ölçülen sorun

Ekrandaki `işten çıkarıldım haklarım nelerdir` sorusu yalnız ihbar ve kötüniyet
tazminatıyla cevaplanıyordu. Bu, embedding'in tamamlanmasını bekleyerek
giderilebilecek tek bir sorun değildi:

- Konu maddesi okuma yolu ilk iki ipucuyla sınırlıydı. Genel haklar özeti için
  ücret, kullanılmayan izin ve feshe itiraz kaynakları plana alınmıyordu.
- Cevabın ana kuralını koruyan denetim `haklarım nelerdir` yazılışını kapsamıyordu.
- Ücretin sona ermede ödenmesine ilişkin cümle m.32'nin ikinci parçasında;
  kaynak başına ilk parçayı seçmek bu asıl cümleyi dışarıda bırakıyordu.
- İki sorulu takip metni reddediliyor, fakat düzeltmeye açıklayıcı kontrol adı
  gönderilmiyordu. Takip sorusunun biçim hatası diğer iddia hatalarını da gizliyordu.
- `bulunması`, `sözleşmeden doğan` ve `sona erdiğinde / sona ermesinde`
  biçimleri bazı doğru açıklamaları yanlış olumsuzluk/koşul farkıyla reddediyordu.

## Değişiklik

Geniş işten çıkarılma hakları sorusunda altı doğrulanmış madde için sınırlı bir
arama planı kullanılıyor: 1475/14; 4857/17, 32, 59, 18, 20. Bunlar hazır cevap
değil, okunacak kaynak adresleridir. Metin yine veritabanından gelir, resmî
doğrulama ve metin beklentisi denetiminden geçer. Gerçek kaynak içindeki ana kural
cümlesini taşıyan parça öncelenir.

Beş mevcut kaynak konusu için kapsam kontrolü var: kıdem, ihbar, ücret, izin,
feshe itiraz. Aynı konunun alternatif maddeleri gereksiz tekrar zorlamaz. Bir-iki
konuyu anlatıp diğer mevcut konuları atlayan taslak tam cevap diye yayımlanmaz.
Eksik kaynak grubu varsa içeriği uydurulmaz ve kısmi kapsam açıkça belirtilir.

Dar, tarihli, açık madde veya içtihat soruları bu geniş plana zorlanmaz.
Kullanıcı belgesi içeren cevaplara bu genel mevzuat kontrol listesi dayatılmaz;
özel kapsamın buluta gönderilmeme kuralı değişmedi.

Takip sorusu ve iddia hataları tek düzeltmeye birlikte iletiliyor. Dilbilgisi
iyileştirmeleri dar biçimlere uygulanıyor; gerçek olumsuzluk, kaldırılan koşul,
uydurulan asgari süre, sayı/birim ve bağımsız denetçi reddi testlerle korunuyor.
Kaynak koşulları veya resmî doğrulama kapatılmadı.

## Doğrulama ve sınırlar

- Son tüm Python testleri: **2328 geçti, 440 atlandı**, bir bağımlılık uyarısı.
  Ağ/DB gerektiren atlanan testler başarılı sayılmıyor. Alt süreçlerde UTF-8
  kullanılmadan yapılan bir önceki koşudaki sekiz CLI çözümleme hatası,
  `PYTHONUTF8=1` ile tekrar sınandı; kaynak dosyaları bu nedenle değiştirilmedi.
- Gerçek RAG hattında, kişisel veri içermeyen aynı soru sohbet kaydedilmeden
  denendi. Son canlı koşu: `openrouter`, `deepseek/deepseek-v4-flash`,
  `grounded=true`, `answer_kind=legal`, beş konu ve altı maddeye atıf.
- Son başarılı canlı koşuda **bir mekanik düzeltme çağrısı gerekti**. Daha önceki
  koşularda bazı taslaklar haklı olarak reddedildi; bir koşu veritabanı bağlantı
  kesintisiyle başarısız oldu. Tek başarı bütün sorularda kararlılık/hız garantisi
  değildir. Anlatımın uzunluğu ve düzeltme maliyeti hâlâ iyileştirme alanıdır.
- Yalnız API yeniden başlatıldı: sağlık 200, Uvicorn başlangıcı doğrulandı,
  `WinError 10048` yok. Tarayıcıdaki kayıtlı eski mesajlar değiştirilmedi;
  bu çalışma oturumlu tarayıcı kabul testi yapmış sayılmaz.
- Ana ANN işi günlükte 21:43'te dışarıdan iptal edilmiş, ardından Docker/DB
  yeniden başlamış ve indeks kaydı kaldırılmıştı. Kullanıcı başka ajanın bakım
  yaptığını doğruladı. Çakışmamak için yeniden kurulum veya DB müdahalesi yapılmadı.
  Bu nedenle ana semantik kolun eksikliği/kısmi tarama uyarısı giderilmiş sayılmaz.

Embedding işçileri, Docker ayarları, ödeme/anahtar ayarları ve .env değiştirilmedi.
İlgisiz çalışma ağacı değişiklikleri korundu; commit/push yapılmadı.
