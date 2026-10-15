# Kaynak okuyucu — 15.10.2026

İçtihat arama kartındaki “Kaynağı aç”, sohbet atıfları, incelenen diğer kaynaklar
ve araştırma kaynakları ortak `SourceReader` penceresini açar. Kullanıcı
belgeleri bu kamusal korpus okuyucusuna gönderilmez. Resmî/kaynak sitesi bağlantısı
ayrı ve isteğe bağlıdır; Yargıtay/Danıştay `getDokuman` uçlarının XML/HTML
gösterebileceği açıklanır. Dış adres otomatik çekilmez veya sunucuda proxy edilmez.

Mevcut `GET /api/legal/sources/{id}` kullanılır. Bu uç yalnız erişime açık hukuk
kaynaklarını getirir; silinmiş/uygun olmayan kaynaklar 404 kalır. Doğrulama
durumu detail yanıtına eklendi; mevcut kaynak uygunluk filtresi değiştirilmedi.
Üçüncü taraf kayda ✓ verilmez, kullanıcı belgesi resmî diye etiketlenmez.
Bu değişiklik migration veya belge taşıma/silme işlemi gerektirmez.

Okuyucu ana kayıt metnini paragraf ve son kısmı kesmeden gösterir. Ana metin
yoksa parçalar açık bir kapsam uyarısıyla sunulur; kısa atıf alıntısı hiçbir
zaman tam metin diye gösterilmez. Kimlik uyuşmazlığı/geçersiz yanıt, 404, ağ
hatası ve 20 saniyelik zaman aşımı ayrı hata/yeniden deneme akışındadır.
Kapanış/kaynak değişimi isteği iptal eder; geç yanıt eski kaydı geri getiremez.
HTML metni React metin düğümü olarak gösterilir, çalıştırılmaz.

## Kabul

- 443 web testi; TypeScript ve üretim derlemesi başarılı.
- İzole, sıfırdan sentetik PostgreSQL'de tam Python paketi: 1721 geçti,
  136 atlandı. Bu koşu tarayıcı opt-in paketini çalıştırmaz; atlananlar başarı
  sayılmaz. Yeni doğrulama etiketi ve silinmiş kaynak reddi DB'de sınandı.
- Değiştirilen web dosyalarında hedefli ESLint temiz. Projenin önceki genel
  lint açıkları bu değişiklikle kapatılmış sayılmaz.
- Ayrı Chromium: kullanıcının belirttiği kamuya açık 2025/6239 E., 2026/2845 K.
  kaydının 4843 karakteri iç okuyucuda açıldı; masaüstü, 390 px mobil taşma,
  Escape ile kapanış ve kontrollü 404'ten yeniden deneme geçti. Page error yok.
  Testteki kasıtlı 404, tarayıcı konsolunda beklenen kaynak hatasıdır.
- İlk tarayıcı fixture denemeleri yerel ağ erişim iznine takıldı. Son kabulde
  yalnız ayrı test bağlamına `localhost:3000` için yerel ağ izni verildi;
  kullanıcının tarayıcı ayarları ve uygulamanın CORS kuralları değiştirilmedi.
- API yeniden başlatıldı; health `ok/database connected`, canlı kaynak detayı
  aynı kimliği ve `verification=official` döndürüyor. Canlı özel veriler değişmedi.

Yerel kanıtlar: `.local/source-reader-web.xml`,
`.local/source-reader-20261015-database.xml`, `.local/source-reader-desktop.png`,
`.local/source-reader-mobile.png`. Tarayıcı fixture'ı
`web/tests/fixtures/source-reader-browser.tsx`; kabul sürücüsü
`.local/check_source_reader_browser.py`.

Bu, kaynak açma akışının kabulüdür; [AI kalite denetimindeki](ai-quality-audit-20261015.md)
belge-soru uyumu ve talimata uygunluk açıklarının kapandığı anlamına gelmez.
Ürünün tamamı için ticari yayın onayı olarak yorumlanmamalıdır.

## Bağlantı taraması — 15.10.2026, ikinci kontrol

İçtihat, ana sohbet, incelenen diğer kaynaklar ve araştırma listesi bağlantıları
yeniden denetlendi. Eksik kalan ana sayfa hızlı sohbeti, AIRunner araştırma
modülleri ve derin araştırma adımları da ortak atıf listesine bağlandı. Kaynaklar
UI için düz Markdown'a dönüştürülmez; kimlik, kaynak türü, alıntı ve doğrulama
durumu korunur. Kopyalama/dışa aktarma metnindeki kaynakça korunur.

Derin araştırmanın hem yeni canlı sonucu hem kayıtlı raporu `source_id` ve
`excerpt` alanlarını taşıyacak şekilde güncellendi. Eski kimliksiz kayıtlar
uydurma eşleştirme yapmaz; okuyucu tam metnin açılamadığını açıkça belirtir.
Özel kullanıcı belgeleri kamusal korpus okuyucusunun dışında kalır.

Bu ek turda 468 web testi, 9 derin araştırma Python testi geçti; 4 DB koşullu
test atlandı. Tür kontrolü başarılı. Ayrı Chromium'da gerçek ortak bileşenlerle
sohbet, incelenen kaynak ve derin araştırma olmak üzere üç akışta aynı kamusal
karar metni açıldı; üç korpus okuması, sıfır özel belge okuması, sıfır dış
gezinme, sıfır sayfa hatası; 390 px mobil görünümde taşma yok.
Kanıtlar `.local/check_source_links_browser.py`,
`.local/source-links-desktop.png`, `.local/source-links-mobile.png`.

Devam eden UYAP aktarımı kesilmedi. Bu turdaki derin araştırma API alanları
çalışan süreçte etkinleştirilmedi; güvenli zamanda API yeniden başlatıldıktan
sonra yeni raporlar kimliği taşıyacaktır. Bu aktivasyon yapılmadan o bölümün
canlı uçtan uca kabulü tamamlanmış sayılmaz.
