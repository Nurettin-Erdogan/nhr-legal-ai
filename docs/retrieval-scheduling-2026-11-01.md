# Arama sıralaması geliştirmesi — 2026-11-01

AWS taşıma/yedekleme işi kullanıcı isteğiyle ertelendi. Mevcut korpusta
kaynak arama gecikmesine odaklanıldı; üretim verisi, indeksler ve model
yönlendirmesi değiştirilmedi.

## Kod değişikliği

Genel arama iki izole vektör işçisini zaten kullanıyor. Üçüncü vektör
arama kolu, dolu yuva durumunda çağıranın bağlantısında hemen çalışıyor ve
kelime aramasının başlamasını geciktiriyordu. Şimdi bu taşan kol aynı
bağlantıda, kelime aramasından sonra çalıştırılıyor. Yeni işçi veya sınırsız
executor kuyruğu yok; SQL, aday limitleri, kaynak/güncellik filtreleri ve
vektör zaman aşımı davranışı korunuyor. Seri/özel kapsam yolu değişmiyor.

Testler; iki işçinin kelime aramasıyla örtüşmesini, üçüncü kolun kelime
aramasını bekletmemesini, tüm kolların korunmasını ve zaman aşımı/eksik
opsiyonel migration durumunda başarılı kaynakların kaybolmamasını kapsıyor.

## Canlı korpus gözlemi

Üretim API'sine istek veya ücretli modele çağrı yapmadan aynı sentetik
sorgularla önceki/yeni fonksiyon davranışı ayrı tanılama sürecinde çalıştırıldı.
Çalışma ağacındaki diğer değişiklikler geri alınmadı. İkinci sorguda ölçüm
sırası ters çevrildi; yine de disk/önbellek ve bakım yükü sabit değildi.

| Sorgu | Önce | Sonra | Kaynak karşılaştırması |
| --- | ---: | ---: | --- |
| İşe iade/işçi sayısı | 30.703 sn | 24.240 sn | 8/8 kaynak ve bütün parçalar aynı |
| Havale/itiraz | 17.666 sn | 15.619 sn | İkisinde de 8 kaynak, 6'sı ortak |

İki sürümde de kısmi sonuç vardı. İkinci sorgunun kelime kolu yeni koşuda
zaman aşımına uğrarken eski koşuda official fallback tamamlandı. Bunun
hangi sonuçları etkilediği daha ayrıntılı incelenmeden kaliteyi koruyan
kesin bir hızlanma veya tamamlanmış düzeltme ilan edilmemeli.

## Doğrulama ve devreye alma durumu

- Tam izole backend paketi: **3653 geçti, atlanan yok**, 198.26 sn.
  Sentetik UYAP tarayıcı dosyası bu ayrı backend paketine dahil değildir.
- Değişen arama dosyaları Ruff kontrolünden geçti; diff whitespace kontrolü temiz.
- Ücretli model/ağ çağrısı yapılmadı. Ağ bariyerindeki tek engelleme,
  engelin çalışmasını bekleyen negatif testti.
- Test için açılan izole veritabanı tekrar kapatıldı.
- Üretim API'si yeniden başlatılmadı; bu kod henüz çalışan API'ye alınmadı.
- Kaynak seçimi kararlılığı ve kelime kolunun I/O kaynaklı zaman aşımı açık
  kalan iştir. Salt daha kısa süre, kabul ölçütü olarak yeterli görülmedi.

Ham karşılaştırma: `.local/retrieval-scheduling-comparison-20261101.json`.
