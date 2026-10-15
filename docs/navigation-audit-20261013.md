# Çalışma alanı ve menü denetimi — 13 Ekim 2026

## Uygulanan düzen

Ana menü 21 bağlantıdan 10 ana giriş ve Ayarlar bağlantısına indirildi:
Ana Sayfa, Hukuk Asistanı, Davalar ve Projeler, Belgeler, UYAP Aktarımı,
İçtihat, Mevzuat, Belge Hazırla, Müvekkiller, İş Takibi.

- Takvim ve hatırlatmalar İş Takibi altında görünüm bağlantılarıdır.
- Davalar, Projeler ve İcra dosyaları aynı çalışma alanından açılır. Kayıtları
  veya birbirinden farklı veri modelleri birleştirilmedi.
- Gelen başvurular Müvekkiller içinden erişilir.
- Kamera ve manuel OCR, belge arşivinin araçlarıdır. Normal yükleme zaten
  arka planda indeksleme/metin çıkarma akışını kullanır.
- Derin araştırma, belge analizi, özet ve risk incelemesi Hukuk Asistanı'nın
  modlarıdır. Eski adresler ilgili moda yönlenir.
- Alt sayfalarda ana menünün ilgili çalışma alanı etkin kalır; etkin grubun
  açık kalması korunur. UYAP ana menüden kaldırılmadı.

## Dosyaya bağlı çalışma

Arşivde veya dava evraklarında seçilen belgeler analiz, özet, risk incelemesi
ve taslak hazırlamaya taşınır. Geçici seçim yalnız kullanıcıya özel oturum
deposunda belge kimlikleriyle tutulur; belge metni URL'ye konmaz. Seçim
30 dakika geçerlidir. Bozuk/başka kullanıcıya ait/süresi dolmuş seçimle
işlem başlatılmaz. Sunucu belge erişimini RLS ile ayrıca doğrular.

Analiz/özet için en çok 4 belge seçilir. Sunucu hazır metin parçalarını
belge bazında toplar; işlem talimatını belge metni gibi özetlemez.
Erişilemeyen, silinmiş veya okunmamış tek bir seçim varsa 409 döner;
kalanları sessizce tamamıymış gibi göstermez. Uzun belgelerin özet
kapsamı mevcut pencereleme hesabıyla sonuçta belirtilir.

Risk incelemesi ve taslak bağlamı halen kısa metin örnekleriyle sınırlıdır;
bu sınır seçim ekranında ve risk çıktısında belirtilir. Taslakta en çok
40 belge seçilebilir. Dava üzerinden açıldığında kayıtlı dosya numarası,
mahkeme, müvekkil ve karşı taraf forma alınır; seçim aynı davayla sınırlanır.
AI modülü sonucu `case_id` ile kaydedilebilir. Taslak kaydının metadata'sı
da ilgili dosya ve belge kimliklerini taşır.

Belge seçicinin ilk 1000 kayıtta kesilmesi giderildi; sıralı sayfalarla tüm
kayıtlar yüklenir. Hesap/dava değişiminde önceki kapsamın listesi gösterilmez.

## Düzenleme ve kamera

Taslak için başlık, kalın/italik yazı, paragraf, madde/numaralı liste ve
geri alma araçları olan düzenleyici eklendi. Düzenlenen metin kaydetme ve
dışa aktarmada kullanılır; Word çıktısında kalın/italik ve madde listesi
korunur. Bu, tam Word sayfa yerleşimi veya değişiklik izleme sistemi değildir.

Eski kamera ekranı `scanner_payload` yazıp hiçbir bileşenin okumadığı bir
veriyi Asistan'a gönderilmiş gibi bildiriyordu. Artık taramayı gerçek PDF
olarak kullanıcının belge arşivine kaydeder; metin arka planda işlenir.
PDF/JPG yerel indirme seçenekleri de korunur.

## Doğrulama

- Frontend: 394 test geçti; TypeScript kontrolü ve üretim derlemesi geçti.
- Python: 1391 test geçti; 385 test ortam koşulları nedeniyle atlandı.
  Atlanan veritabanı ve opt-in tarayıcı testleri başarılı sayılmadı.
- Yerel API güncel kaynakla yeniden başlatıldı; `/health` 200 ve toplu
  çöp rotası OpenAPI'de mevcut. Web Asistan/Belgeler sayfaları 200 döndü.
- Kullanıcı belgeleriyle canlı analiz, yeni tarama yükleme veya silme
  işlemi yapılmadı. Chrome bağlantısı yoktu; bilgisayar penceresi erişim
  onayı da zaman aşımına uğradı. Son görsel/tıklama kabul turu tamamlanmadı.

## Kalan açıklar ve öncelik

> Aşağıdaki liste ilk menü denetiminin tarihsel sonucudur. Aynı gün devamında
> kalıcı tam metin kuyruğu, Drive içe aktarımı, Word görev bölmesi ve sayfa
> düzeni eklendi; canlı sentetik özet ve düzenleyici kontrolü yapıldı.
> Güncel kapsam, kurulum gereksinimleri ve sınırlar için
> [belge çalışma alanı raporuna](document-workspace-20261013.md) bakın.

1. Canlı hesapta yeni menü, belge seçimi, düzenleyici ve dar ekran akışının
   görsel/tıklama kabul turu; ayrı test DB'sinde RLS bütünleşik testleri.
2. Büyük belge setlerinde arka plan özet kuyruğu: hızlı mod 4 belgeyle
   sınırlı; dava özetinin de kendi iş/pencere sınırları vardır. Tam dosya
   incelendiği iddiası bu sınırlara rağmen verilmemeli.
3. Risk ve taslakta örnek metin yerine daha geniş belge kapsamı; sonuçların
   kaydedilen ilgili dava/proje ekranından kesintisiz bulunması.
4. Gelişmiş editör: sayfa düzeni, değişiklik izleme, tam PDF biçim koruma
   ve doğrulanmış UDF dışa aktarma mevcut değil.
5. Word/Google Drive ürün entegrasyonları halen yok. Menü düzenlemesi
   bunları eklemez; ayrı bağlantı, erişim ve kabul akışı gerektirir.
6. UYAP aktarımının son canlı kabul testi bu çalışmanın kapsamına alınmadı;
   bu düzenleme aktarımın hatasız olduğunu kanıtlamaz.

Apilex'e ilişkin referanslar ürün anlatımıdır; giriş sonrası arayüz ve
performans bu çalışmada ölçülmedi:
[Asistan](https://www.apilex.ai/tr/asistan),
[Projeler](https://www.apilex.ai/tr/akilli-belge-yazim-platformu),
[Platform](https://www.apilex.ai/tr/platform).
