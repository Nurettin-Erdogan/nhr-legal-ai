# UYAP yayın kontrol listesi — 2.26.10

Tarih: 2026-10-05. Kapsam: kullanıcıya özel UYAP aktarımı, elle içe aktarma,
dava eşleştirme ve eklenti köprüsü. Merkezî hukuk korpusu ve veri toplama worker'ları
bu değişikliğin kapsamı değildir. Bu dosya gerçek hesap verisi veya bağlantı anahtarı içermez.

## Karar

**Otomatik testleri geçen yayın adayı; halka açık ticari yayın onayı henüz verilmedi.**
Canlı Vatandaş/Avukat kabul testi ve gerçek HTTPS adresleriyle dağıtım kontrolü
tamamlanmadan "bütün UYAP dosyaları sorunsuz çekilir" denemez. Bu tur gerçek kullanıcı
belgesi yüklenmedi, silinmedi veya yeniden ilişkilendirilmedi.

## Tamamlanan düzeltmeler

1. ODT ve karışık PDF/ODT arşivi elle aktarılır; başarısız üyeler ayrı raporlanır.
2. Eşzamanlı elle aktarım sunucuda atomik mükerrerlik kontrolünden geçer.
3. Ters dava sıralı toplu eşleştirme ve eşzamanlı yükleme ortak sahip kilidiyle çalışır.
4. Esas numarasındaki boşluklar yeni kayıtta ve eski kayıt karşılaştırmasında normalleştirilir.
5. Aynı evrak kimliği/içeriği farklı görünen adla tekrar gelince yeni belge oluşturulmaz.
6. Dava-belge müvekkil çelişkisi ilişkiyi değiştirmeden bildirilir; açık belge müvekkili korunur.
7. Geçersiz takvim tarihi yazılmaz; geçerli artık yıl ve ISO tarihleri korunur.
8. Bilinen evrakları atlama sorgusu mahkeme/birimle kapsamlanır; başka mahkeme karışmaz.

Değişiklikler mevcut mükerrerleri topluca silmez veya değişmiş evrakı otomatik olarak
eski belgenin üzerine yazmaz. Çelişen ilişki için kullanıcı incelemesi gerekir.

## Otomatik kanıt

| Kontrol | Sonuç | Sınır |
| --- | --- | --- |
| Tam Python regresyonu | 1.204 geçti, 88 atlandı | Ayrı `*_test` veritabanı; atlanan 87 tarayıcı testi ayrıca çalıştırıldı. Kalan 1 testin yerel veri fixture'ı yok. |
| Gerçek DB/HTTP eşzamanlılık | 4 geçti; yukarıdaki toplama dahil | Gerçek `nhr_runtime`, RLS, ayrı bağlantılar, sentetik kullanıcı; yalnız üretilen test kayıtları temizlenir. |
| Web regresyonu | 161 geçti | API istemcisi, durum mesajları, ZIP/kaynak uyumu dahil. |
| TypeScript ve üretim derlemesi | Geçti | Derleme canlı dağıtım değildir. Vite yapılandırması/paket boyutu uyarıları kaldı. |
| Chromium eklenti senaryoları | 87 geçti; 13 dakika 13 saniye | Gerçek Chromium + yerel sahte UYAP/API; gerçek portal erişim yetkisini ve DOM'unu kanıtlamaz. |

Yerel ayrıntılı Python raporları `.local/uyap-release-regression.xml` ve
`.local/uyap-release-browser.xml` içindedir. GitHub CI'ya izole Chromium işi eklendi;
bu tur GitHub'da çalıştırılmadı, commit/push yapılmadı.

Yeniden çalıştırma (yalnız hazırlanmış ayrı test veritabanıyla):

```powershell
$env:NHR_TEST_DATABASE_URL = '<yalnız *_test veritabanının bağlantısı>'
.\.venv\Scripts\python.exe -m pytest -q
$env:NHR_BROWSER_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_uyap_extension_browser.py -q
```

Web: `web/` içinde `npm test`, `npm run typecheck`, `npm run build`.
Eklenti paketini değiştirdikten sonra `npm run package:extensions` ve paket/kaynak
eşitliği testleri tekrar çalıştırılır.

Yerel servis kontrolü: son kodla API 8766 ve web 3000 yeniden başlatıldı. `/health`
200 / `database=connected`, anonim elle aktarım 401, `/dashboard/uyap` 200,
eklenti manifesti 200 / `version=2.26.10`, indirilebilir ZIP 200 olarak doğrulandı.
Uzun süredir açık geliştirme sunucusu başlangıçta manifest için 404 döndürüyordu;
yeniden başlatmadan sonra düzeldi. Canlı DB'deki iki mükerrerlik indeksinde de
`uyap_birim` kapsamı salt okunur kontrolle doğrulandı; bu tur migration uygulanmadı.

## Kurulum ve geri dönüş

1. Veritabanı ve belge deposunun geri yüklenebilir yedeğini doğrula. Mevcut kuruluma
   `database/migrations/046_uyap_court_identity.sql` uygulanmış olmalı; yeni kurulum
   karşılığı `database/init/047_uyap_court_identity.sql`. Migration birim kapsamlı
   mükerrerlik indekslerini düzenler; bu sürüm ilave DDL gerektirmez.
2. API'yi yeni kodla yeniden başlat. Sağlık ve DB bağlantısını, anonim
   `/api/office/uyap/import` isteğinin 401 olduğunu kontrol et.
3. Web'i aynı sürümle yayımla; eski açık web sayfasını yenile. Artık eski genel
   UYAP satır ekleme yolu 409 verir; yeni oturumlu multipart yolu kullanılmalıdır.
4. `web/public/jurisai-avukat.zip` 2.26.10 paketini kur/güncelle, hizmet çalışanını
   ve JurisAI/UYAP sekmelerini yenile. Anahtar yalnız gerektiğinde, kullanıcı onayıyla
   yenilenir; token loglara veya rapora yazılmaz.
5. Aşağıdaki canlı kabul adımlarını önce tek evrak, ardından onaylı küçük grup ile
   bitir. Tamamlanmayan aktarım yeşil tam başarı olarak görünmemelidir.
6. Geri dönüş gerekiyorsa API/web/eklenti üçlüsünü uyumlu son sürüme döndür;
   belge silme, kaydı yeniden yazma veya toplu tekrar aktarım yapma. Bu sürüm için
   veri tabanı downgrade gerekmez. Anahtar geri dönüşü yapılmaz; yenilenmiş eski anahtar
   güvenlik nedeniyle geçersiz kalır.

## Yayın öncesi açık kapılar

- [ ] **Bu sürümle gerçek Vatandaş Portalı:** hesap sahibinin onayıyla tek evrak
  aktar; indirilen içerikte esas/birim/tarihi portalla karşılaştır. Yeniden tarama
  ve tekrar aktarımda tek kayıt/tek belge kimliği korunduğunu doğrula. HTML/kısa
  hata yanıtının belge diye kaydedilmediğini kontrol et.
- [ ] **Gerçek Avukat Portalı:** yetkili avukat hesabıyla liste, sonraki sayfa,
  evrak ağacı, ekler ve onaylı aktarımı ayrı doğrula. Vatandaş testinden bu sonucu çıkarma.
- [ ] **Toplu canlı test:** geçerli ODT/PDF/UDF, ZIP ek, kalıcı yetki hatası,
  oturum kapanması, durdurma ve yeniden tarama; bulunan/aktarılan/zaten olan/hatalı
  sayılarının tutarlılığını kontrol et. Portalın izin vermediği evrak garanti edilemez.
- [ ] **Yayın alan adları:** gerçek HTTPS web/API adresleri henüz belirtilmedi.
  Eklenti `manifest.json` içerik/host eşleşmeleri, `background.js` `WEB_ORIGINS`,
  API adresi ve API `CORS_ORIGINS` aynı gerçek adreslerle dar kapsamlı ayarlanmalı.
  `localhost:3000/8766` varsayımlarıyla halka açık dağıtım yapılmamalı.
- [ ] **Dağıtım:** Chrome Web Store paketi/izin açıklamaları ve aynı sürümle temiz
  profil kurulumu doğrulanmalı. Geliştirici modunda ZIP kurulum ticari dağıtımın kabulü değildir.
- [ ] **KVKK ve portal koşulları:** mevcut taslak aydınlatma/saklama metinleri,
  veri sorumlusu bilgileri ve UYAP kullanım koşulları yetkili hukuk incelemesinden geçmeli.
- [ ] **İşletim:** üretim TLS, secret yönetimi, yedekten geri yükleme ve saklama/silme
  işlemleri; beklenen yükte aktarım süresi/disk kapasitesi ölçümü doğrulanmalı.

Bu tur canlı kabul testi için kullanılan `computer-use` bağlantısı Windows
`CreateProcessWithLogonW failed: 2` hatasıyla açılamadı. Sahte portal testini canlı
aktarılmış evrak gibi sunmadık. Bağlantı düzeldiğinde açık canlı adımlar sürdürülmelidir.
