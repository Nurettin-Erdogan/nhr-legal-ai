# UYAP tekrar başlama incelemesi — 15 Ekim 2026

Sonraki hedefli canlı teşhis, düzeltme ve test durumu:
[16 Ekim kabul notu](uyap-acceptance-20261016.md). Aşağıdaki geri alma
kaydı tarihçedir; sonraki hedefli düzeltmelerin geri alındığı anlamına gelmez.

## Son durum: kullanıcının isteğiyle geri alındı

Kullanıcı önceki akışın daha iyi çalıştığını belirterek geri dönüş istedi.
`web/src/lib/uyap-sync-all.ts` ve `web/tests/uyap-sync-all.test.mjs`
bu incelemeden önceki HEAD içeriğine döndürüldü. Bu incelemede eklenen
yedi regresyon testi etkin test dizininden kaldırıldı; kaynak ve test
yedekleri `.local/uyap-recovery-review/` içinde saklandı. AI tarafındaki
diğer geliştirmeler korunuyor. Yeni yükleme-hız adayı yalnız
`.local/uyap-speed-review/` içinde; uygulamaya veya eklenti paketine
uygulanmadı.

Geri dönen akışın tüm web testleri **468/468** geçti. Eklenti sürümü
**2.26.35** olarak kaldı. Aşağıdaki “uygulanan düzeltme” ve 475 test
sonucu, geri almadan önceki tarihsel durumu anlatır; şu an etkin değildir.

Canlı koşu durdurulduğunda beş dosyanın toplam **1115/1115** evrakı
kayıtlı görünüyordu; o doğrulama çalışmasında **0 yeni evrak** gönderilmişti.
Bu, mevcut belgelerin kaybolmadığına dair görünür kanıttır; tüm 64
dosyanın eksiksizliği anlamına gelmez. Belge/veritabanı temizliği yapılmadı.

### Geri dönüş sonrası canlı test

JurisAI sayfası tam yenilenerek önceki sayfa görevleri kapatıldı. Liste
yeniden okundu; bu hesapta görünür 64 dosyanın kaydı henüz doğrulanmamış
12 tanesi, kullanıcının “belgeleri koru ve kalanlarla test et” onayıyla
seçildi. Diğer dosyalar için yeniden toplu aktarım başlatılmadı.

İlk sekiz dosyanın yedisinde evrak sonucu eksiksiz göründü. Bir dosyada
`Ek 1: Desteklenmeyen dosya türü (.bin)` hatasıyla 435/436 evrak kaldı.
Dokuzuncu dosyada tek evrakın aktarımı sürüyordu. Bu canlı sonuç,
geri dönüşün bütün hataları çözdüğü anlamına gelmez. `.bin` ifadesi
belgenin gerçek biçimini kanıtlamaz: genel MIME/eksik dosya adı için
eklenti bu uzantıyı kullanabiliyor; içeriği ayrıca teşhis edilmeli.
Bu turda aktif aktarım sürerken yeni kod veya eklenti uygulanmadı.

## Canlı gözlem ve sınır

UYAP Vatandaş oturumu ve açık bir icra dosyasının evrak ağacı okunabildi.
JurisAI'nin kullanıcının mevcut sekmesine kontrol bağlantısı yanıt vermedi.
Mevcut sekme yenilenmeden ayrı bir salt okunur kontrol sekmesi açıldı;
eklenti **v2.26.35** olarak algılandı. Bu yeni sekmenin kendi çalışma durumu,
eski sekmede aktarım olmadığına kanıt değildir.

Web sunucusu Vite geliştirme sunucusudur. İçe aktarılan kaynak kodunu
değiştirmek canlı sayfayı yenileyebilir. Kullanıcı **"Aktarım durmuş,
düzeltmeleri uygula"** diye onayladıktan sonra düzeltme gerçek kaynak
dosyasına uygulandı. Belge, hesap ve bağlantı anahtarı değiştirilmedi;
API veya UYAP oturumu yeniden başlatılmadı.

## Yeniden üretilen hatalar

1. `syncAll` ölümcül hatadan sonra okunabilen herhangi bir listeyi toparlanma
   kabul ediyor. Aynı dosya tekrar hata verse de dosya başına sınır yok.
2. `pairing_rejected`, `no_uyap_tab`, `no_content`, `idle` gibi farklı nedenler
   de UYAP yeniden giriş beklemesine giriyor. Yeniden giriş bunları çözmez.
3. İstenen dosya bulunmayan veya aynı kimlik için iki satır bulunan liste
   toparlanma kanıtı kabul ediliyor. Boş liste de üçlü hata toparlamasında
   başarılı sayılıyor.
4. Evraklar gönderilip dosya bilgisi okunurken oturum kaybolursa rapor
   sıfırlanıyor; yeniden okumada `sent`/`pulls` önceki başarılı gönderimleri
   kaybediyor. Bu, sunucudaki evrakların silindiği anlamına gelmez.

## Uygulanan düzeltme

İlk aday izole klasörde sınandı. Düzeltme artık
`web/src/lib/uyap-sync-all.ts` dosyasındadır; otomatik testleri
`web/tests/uyap-session-recovery.test.mjs` içindedir.

- Aynı dosyada en fazla iki oturum toparlanması; devam eden hata açık
  nedenle durur, kalanlar işlenmedi olarak kalır.
- Yalnız oturum/iş/listenin kaybı için yeniden giriş beklenir.
- Yeni listede hedef dosya tam kimliğiyle tekil bulunmalıdır.
- Gönderim ve çekim sayaçları yeniden denemeler boyunca birikir;
  başarısız raporlar tekrar başlamadan önce silinmez.
- Yeniden listeleme sırasında iptal edilirse yeni dosya işi başlatılmaz.
- Son eksik evrak turunda da sayaçlar ve ara kayıt korunur. Bu turda
  gönderilen bir evrak, son doğrulaması başarısızsa eksiksiz sayılmaz.

## Doğrulama

- Tüm web testleri: **475 geçti** (son düzeltme uygulanmış hâli).
- UYAP API birim testleri: **59 geçti, 44 atlandı**. Atlananlar gerçek
  veritabanı gerektirir; bu taramada canlı veritabanına yazılmadı.
- İlk beş regresyon testi eski kodda **4 hata / 1 geçiş** üretti;
  düzeltmeyle **5/5 geçti**. Son tur sayaçları için iki ek testle
  yeni test sayısı **7/7**, toplam orkestratör testi **53/53** oldu.
- Boş listenin başarılı toparlanma kabul edildiği eski davranışı
  bekleyen test, doğru erken durma davranışı için üç çağrıya güncellendi.
- Gerçek kaynak dosyasıyla tam proje TypeScript kontrolü ve üretim
  derlemesi başarılı.

## Sonraki adım

Değişiklik arayüz orkestratöründedir; eklenti sürümü değiştirilmedi,
yeniden eklenti kurmak gerekmez. JurisAI sayfası yenilendikten sonra
güncel listeyle yalnız eksik evraklara sınırlı canlı kabul testi yapılmalı.
Bu turda yeni özel evrak aktarımı başlatılmadı. Otomatik testlerin
geçmesi bütün gerçek evrakların eksiksiz aktarıldığına veya UYAP'ın her
zaman yanıt vereceğine kanıt değildir.
