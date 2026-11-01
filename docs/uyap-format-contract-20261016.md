# UYAP: türden bağımsız arşivleme ile metin işlemeyi ayırma

## Amaç ve sınır

Hesap/mahkeme/evrak adı için ayrı istisnalar eklemek yerine, aynı aktarım
sözleşmesi bütün hesaplarda uygulanır. **Kaydedildi**, **metni çıkarıldı** ve
**aranabilir** aynı sonuç değildir. Bu değişiklik her formatın içeriğinin
okunabildiği veya UYAP'ın her isteğe yanıt vereceği anlamına gelmez.

## Akış

1. Eklenti yalnız izinli HTTPS UYAP/Adalet alanından yanıt alır; HTTP hatası,
   eksik gövde, oturum/erişim/indirme doğrulama yanıtı başarı sayılmaz.
2. Bilinen binary imzaları, MIME ve Content-Disposition mevcut adlandırma
   akışında değerlendirilir. Tanınmayan tür PDF olarak adlandırılmaz.
3. Tanınmayan ekler son uzantısı `.bin` olan arşiv adına yönlendirilir;
   güvenli özgün uzantı adın içinde korunur (`Attachment.customformat.bin`).
   Bu ad, tam özgün Unicode dosya adının korunması iddiası değildir; mevcut
   dosya adı güvenliği normalizasyonu devam eder.
4. Modern multipart yükleme ucu, bağlantı anahtarını **gövdeyi okumadan önce**
   doğrular. Bilinmeyen tür yalnız geçerli dosya numarası, birim ve kalıcı
   evrak kimliğiyle arşivlenir. Genel dosya yükleme/legacy JSON izin listesi
   genişletilmez. Dosya çalıştırılmaz veya inline sunulmaz.
5. Özgün baytlar ve SHA-256 korunur; mevcut sahip RLS'si, kimlik+checksum
   tekilleştirmesi ve denetim kaydı aynen uygulanır. `.bin` yanıtı
   `archiveOnly: true, searchable: false` bildirir.
6. `.bin` için önizleme/metin çıkarma yapılmaz; büyük gövde indeksleme için
   RAM'e alınmaz. Arama kaydı `ready` olmaz; mevcut `failed` durumu altında
   "Özgün dosya arşivlendi ... İçeriği aranabilir değil" açıklaması tutulur.
   Bu durumun ayrı bir UI arşiv rozetiyle gösterilmesi sonraki tasarım işidir.
7. Dosya yalnız sahibine, `Content-Disposition: attachment`, octet-stream
   ve `X-Content-Type-Options: nosniff` ile indirilir. Bilinmeyen/çalıştırılabilir
   dosyaların `.bin` olarak saklanması zararsızlık veya antivirüs taraması değildir;
   kullanıcı bunları ayrıca açmaya/çalıştırmaya yönlendirilmez.

## HTML, KEP ve kısa metin

- KEP/makbuz tanıma artık `Ek`, `Diğer Evrak`, `Bankadan Gelen Cevap Yazısı`
  gibi değişken ağaç başlıklarına bağlı değildir. İçerikteki tam pasif belge
  yapısı aranır. Başlık tek başına hiçbir yanıtı belge yapmaz.
- Generic HTML yalnız açık attachment disposition ve uygun HTML dosya adıyla,
  pasif içerik ve giriş/hata denetimleri geçince kabul edilir. Diğer HTML
  sayfaları bilinmeyen binary arşiv yoluna düşmez. HTML içerik denetimi için
  mevcut 1 MiB sınırı korunur; etkin/çok büyük HTML için genel kabul yoktur.
- Gerçek kısa TXT/CSV/EML/RTF attachment, sadece kısa olduğu için hata sayılmaz.
- BOM'lu UTF-16 ve baştaki HTML yorumları hata sayfasını binary olarak gizleyemez.
- HTTP 200 JSON hata zarfı (açık gerçek attachment değilse) ve generic MIME
  altında gelen açık oturum/erişim mesajı başarı sayılmaz.
- Bu kontroller portalın kriptografik doğrulaması veya kötü amaçlı dosya taraması
  değildir. Tüm bilinmeyen içeriklerin zararsız olduğu iddia edilmez.

## Test kanıtı

Gerçek hesap içerikleri fixture yapılmadı; tüm format verileri sentetiktir.

- Tam çevrimdışı Python: **1560 geçti, 398 atlandı**; bağımlılık uyarısı mevcut.
- Ayrı, boş test DB'sinde UYAP/API/RLS: **194 geçti**; 142 browser testi
  bu komuttan ayrı tutuldu. Yalnız bu koşunun oluşturduğu test DB'si kaldırıldı.
- Hedefli gerçek Chromium eklenti laboratuvarı: **16 geçti**, 126 seçilmedi.
  KEP farklı başlıklar, makbuzlar, sahte giriş/hata sayfaları, generic MIME
  ve özgün opaque ek baytlarının GET→multipart POST aktarımı test edildi.
- Web sözleşme testleri: **527/527 geçti**; canlı ZIP/source eşitliği testleri
  yayın paketi henüz yükseltilmediğinden ayrı tutulur. Aday ZIP'in 14 girdisi
  güncel incelenen kaynakla (yalnız manifest sürümü 2.26.36) birebir doğrulandı.
- Opaque byte round-trip, SHA-256, tekrar yükleme, farklı sahibin RLS ve dosya
  indirme reddi, attachment/nosniff ve sıfır arama parçası gerçek test DB'sinde
  doğrulandı. Bilinen türlerin parser testleri tam Python koşusunda çalıştı.

## Canlı sınır

Kullanıcının son raporu: 64 dosya, 10189 bulunan/10177 kayıtlı evrak;
3 dosyada 12 evrak ve 4 dosyanın bilgileri eksik; birlikte tam 58/64.
Bu rapor yeni değişikliklerin kabul sonucu değildir.

Kullanıcı aktarımın bittiğini bildirdi; sonraki salt okunur Chrome kontrolünde
arayüz hâlâ 3/6, 2024/196 ve Durdur gösterdi. Bu çelişki nedeniyle API yeniden
başlatılmadı, kurulu eklenti değiştirilmedi, yeni iş başlatılmadı ve mevcut belge
silinmedi. Yeni kaynaklar ayrı v2.26.36 aday ZIP'inde paketlenir; canlı indirme
manifesti/ZIP'i ve kurulu v2.26.35 bundan ayrı tutulur. Canlı kabul beklemektedir.
