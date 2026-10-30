# Kaynak aramasındaki kısa devre — 27 Ekim 2026

## Ölçüm

Özel veri içermeyen tek kira sorusu kullanıldı; kayıtlı sohbetlere yazılmadı.
Gerçek yerel arama + sahte üretim kontrolünde 49 aday bulundu, ilk seçici yalnız
TBK 315'i bırakıyordu. İlk soğuk çalışma 13,53 saniye, sıcak çalışma yaklaşık
1–2 saniye sürdü. Bu kontrollerde ücretli üretim yapılmadı.

Kontrollü canlı çalışmada Luna çağrıları başarılıydı; 31,68 saniyede kısmi cevap
geldi. Önceki dakikalar süren çalışmanın nedeni bu turda tekrarlanmadı. Yerel
geri dönüşün 180 saniyelik çağrı ayarı potansiyel bir gecikme kaynağıdır ancak
önceki olayın kesin nedeni olarak doğrulanmadı; üretim geri dönüş politikası
değiştirilmedi.

## Düzeltilen nedenler

- Konu ipucuyla bir madde bulunması mevzuat anlam aramasını tamamen kapatıyordu.
  Genel sohbetin alt-soru aramalarında `expand_legislation=True` ile diğer
  mevzuat da aranıyor. Açık madde isteklerinin kesin lookup yolu değişmedi.
- Kaynak şeritlerinin içinde aynı maddenin birden çok parçası diğer maddeleri
  dışlıyordu. Önce kaynak çeşitliliği, ardından ek parçalar seçiliyor.
- Genel arabuluculuk usulünün 6325 m.18/A ve 18/B arama adresleri konu tablosunda
  yoktu. Bunlar yalnız adres olarak eklendi; metin yine güncel/doğrulanmış
  korpustan ve metin eşleşme kontrolüyle alınıyor. Cevap sabit kodlanmadı.

## Sonuç ve kalan eksik

Son canlı kontrol 40,48 saniye sürdü. Cevapta TBK 315 ile 6325 m.18/A kaynaklı
arabuluculuk başvuru/son tutanak usulü yer aldı; cevap hâlâ kısmi olarak
işaretliydi. Otuz günlük ödeme süresi ve arabuluculuğun somut kapsamdaki
zorunluluğu eksiksiz son cevapta korunmadı. Bu kabul örneği **başarılı değil**.
Denetim kapıları gevşetilmedi. Sonraki adım kaynak birimi–iddia eşleştirmesi ve
alt-soru kapsamının korunmasını çevrimdışı fixture ile incelemektir.

Tam çevrimdışı takım: 2600 geçti, 442 atlandı (üç ek konu testi eklenmeden önce).
Ek konu testleri ve ilgili regresyonlar ayrıca çalıştırıldı. Ağ bariyeri aktif.
DB gerektiren atlanmış testler çalıştırılmış gibi sayılmıyor. Commit yapılmadı.
