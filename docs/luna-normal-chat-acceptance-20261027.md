# Luna normal sohbet kabul kontrolü — 27 Ekim 2026

## Yöntem

OpenRouter üzerinden `openai/gpt-6-luna`, normal üretim profili ve gerçek yerel
hukuk veritabanı kullanıldı. Derin araştırmanın bulut kullanımı kapalıydı.
Sentetik genel sorular `pipeline.execute_answer(request, None)` ile çalıştırıldı;
özel belge, dava ve kullanıcı sohbeti gönderilmedi, kayıtlı sohbetlere yazılmadı.
Bu koşu HTTP kimlik doğrulamasını, arayüzü veya kaydedilmiş sohbetin canlı devamını
uçtan uca sınamaz.

İlk kısıtlı test sürecinde bulut erişimi başarısız oldu. Bu üç sağlayıcı hatası
Luna kalitesi olarak değerlendirilmedi. Anahtarın ücretsiz durum sorgusu başarılı
olduktan sonra yalnız üç hukuk sorusu ağ erişimi olan süreçte yeniden çalıştırıldı.
Anahtar, ham sağlayıcı hatası ve özel bilgiler rapora alınmadı.

## Sonuçlar

| Senaryo | Gözlem | Değerlendirme |
| --- | --- | --- |
| Merhaba | Uygulamanın selamlaşma cevabı; model çağrısı yok | Geçti |
| Pizza tarifi | Hukuk dışı soru olarak reddedildi; model çağrısı yok | Geçti |
| 18.000 TL kiraya yüzde 20 artış yaparsam kaç TL olur? | 21.600 TL sonucunu vermedi; TBK 344 metnini döndürdü, 7,78 sn | Başarısız |
| TÜFE nedir? Kısa ve anlaşılır açıkla. | Luna kaynaklı kısa tanım verdi; `grounded=true`, 16,53 sn | Bu örnek geçti |
| Ödenmeyen konut kirası: ihtar, ödeme süresi, zorunlu arabuluculuk | İhtar/ödeme süresini verdi; arabuluculuk bölümü yok, kısmi cevap uyarısı var; 29,71 sn | Eksik |
| Üç yıl çalışma sonrası kıdem ve ihbarın birlikte alınması ve istisnalar | Kaynak bulundu, fakat iki üretim denemesinden sonra bütün iddialar elendi; 36,94 sn | Başarısız |

`grounded=true`, hukuki doğruluğun bağımsız uzman değerlendirmesi değildir.
Kira örneğinde kaynaklı kalan kısmın varlığı, sorunun tamamının cevaplandığı
anlamına gelmez.

## Somut tanılar

- Yüzde hesabında açık miktar/oran olmasına rağmen `rent_percentage_reply`
  doğal yazımı kabul etmedi. `kaç TL`, `kiraya`, `yaparsam` gibi biçimler dar
  sözcük dilbilgisinin dışına düşebiliyor. Sonraki hesap/kanıt yolu da beklenen
  sayısal sonucu korumadı. Bu, Luna'dan bağımsız olarak yeniden üretildi.
- Kira sorusundaki ipuçları yalnız TBK 315 ve 352'yi önerdi. Eksik arabuluculuk
  kaynağı olan **6325 m.18/B veritabanında gerçekten mevcut** ve doğrudan
  getirilebiliyor (2007 karakter). Dolayısıyla bu örneği yalnız veri yokluğuyla
  açıklamak yanlış olur; çok konulu kaynak seçimi incelenmeli.
- Kira taslağında beş cümlenin ikisi kaldı, üçü anlamsal denetimde reddedildi;
  `coverage_preserved=false`, `partial_answer=true` kaydedildi.
- İş hukuku örneğinde bir iddia anlamsal denetimde, diğerleri sayı/mutlaklık
  denetimlerinde elendi (`minimum_added`, `unsupported_absolute`). Bu, tek
  başına denetçinin hatalı olduğunu kanıtlamaz: taslak ve ona bağlanan kanıt
  birlikte incelenmeden güvenlik denetimleri gevşetilmemeli.
- Genel aramalarda bazı koşular `retrieval_partial=true` döndürdü.

## Ücretsiz kontroller ve maliyet

Sohbet geçmişi/kullanıcı olguları regresyonlarında **68 test geçti**; ağ engeli
etkindi ve gerçek ağ girişimi sıfırdı. Bu sonuç canlı, kayıtlı sohbet testi değildir.

Canlı test aralığında OpenRouter anahtarı kullanım artışı **0,008906425 USD**;
son sorguda anahtarın limitinde kalan **0,655937289 USD**. Bu anahtarın kullanım
farkıdır; hesap genelindeki tüm harcamaları veya eşzamanlı başka çağrıları ayrı
ayrı muhasebeleştirmez. Ödeme veya limit ayarı değiştirilmedi.

Üretim kodu/ayarları bu kabul kontrolünde değiştirilmedi. Test yardımcısı
git dışındaki `.local/luna_acceptance_20261027.py` dosyasında. Commit yok.

## Sonraki çalışma

Önce doğal yüzde-hesabı yönlendirmesi ve sayısal sonucun korunması; ardından
çok parçalı sorularda her alt konu için mevzuat kanıtı seçimi ve üretim/denetim
uyuşmazlığının yeniden üretilebilir regresyonları. Her örnek için tekrar tekrar
ücretli çağrı yerine önce yerel kanıt ve sahte sağlayıcı testleri kullanılmalı.
