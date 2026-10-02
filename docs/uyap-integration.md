# UYAP entegrasyonu

UYAP'ın avukatlara açık bir API'si yoktur. Entegrasyon, avukatın **kendi açık UYAP oturumunu**
kullanan bir Chrome eklentisine dayanır; şifre ve e-imza bilgisi hiçbir zaman okunmaz veya
sunucuya gönderilmez. Aktarılan belgeler `office_case_documents` tablosuna, yalnız sahibine
görünecek şekilde (RLS) yazılır. İndeksleme ve belgeden soru-cevap için bkz.
[office-workspace.md](office-workspace.md) ve `api/document_indexing.py`.

## Eklentiler

| Klasör | Hedef | Aktarım |
| --- | --- | --- |
| `web/public/jurisai-avukat` | UYAP Avukat Portalı | `POST /api/public/v1/documents/upload` (Bearer anahtar) |
| `web/public/uyap-dosya-cekici` | UYAP Vatandaş Portalı | `POST /api/public/uyap-ingest` (anahtar gövdede); yalnız ayar penceresindeki düğmelerle çalışır |
| `web/public/uyap-extension` | Arayüzde sunulmuyor | `POST /api/public/uyap-ingest` |

İndirilen zip'ler (`web/public/*.zip`) klasörlerle birebir aynı tutulmalıdır; eklenti değişince zip
yeniden oluşturulur.

## Gizlilik varsayılanları (Avukat Portalı eklentisi, v2.9.0)

- **Otomatik aktarım kapalıdır.** Açılırsa (ayar penceresinde, bilgilendirme onayıyla) UYAP'ta bir
  dosya görüntülenince evraklar ve künye (mahkeme, esas no, **taraf adı**) kendiliğinden gönderilir.
  Kapalıyken yalnız düğmeye basılan evrak gider; arka plan betiği de ayar kapalıyken otomatik
  aktarım isteğini reddeder.
- **Yerel kopya kapalıdır.** Açılırsa her belge `İndirilenler/NHR-Hukuk-UYAP` içine de kaydedilir.
- **Toplu aktarım onay ister.**
- Düğmeler yalnız esas numarası olan bir dosya sayfasında, tek bir evrak satırında çıkar; giriş ve
  ana sayfalarda çıkmaz.

## Sunucu uçları: güvenlik notları

- Kimliksiz genel uçlar gövdeyi kimlik doğrulamadan önce okuduğundan `/uyap-ingest` gövdesi 100 MB,
  çok parçalı yükleme 51 MB ile sınırlıdır; çok parçalı gövde anahtar doğrulandıktan sonra ayrıştırılır.
- Yinelenen belge denetimi `dosya adı + boyut + UYAP dosya numarası` iledir (farklı davalardaki aynı
  adlı belge kaybolmaz). Aynı davada aynı adlı ve aynı boyutlu farklı içerik yinelenen sayılır; bunun
  için içerik özeti (hash) gerekir.
- Geçerli anahtar + dosyasız istek `400 {"error": "Dosya eksik"}` döner; eklentinin "Bağlantıyı dene"
  düğmesi bunu bekler.

## Bağlantı anahtarı

Anahtar (`jsai_…`) veritabanında **düz saklanmaz**: yalnız SHA-256 özeti (`token_hash`) ve gösterim için
ilk 9 karakter (`token_prefix`) tutulur. Bir tetikleyici (migration 033) eklenen düz değeri özetleyip
siler; 32 karakterden kısa anahtarı reddeder; özet ve ön ek sonradan değiştirilemez (yenileme =
eskisini `revoked` yapıp yenisini eklemek). Arayüz anahtarı **yalnız oluşturulduğu anda** gösterir;
sonrasında ön ek ve son kullanım zamanı görünür, kaybedilen anahtar için "Anahtarı yenile" kullanılır.
Migration var olan anahtarları özetledi: eklentilerdeki değerler çalışmaya devam eder.

## Sayfa tanısı (gerçek UYAP'ta seçiciler tutmazsa)

Avukat Portalı eklentisi (v2.8.0) popup'ında **"Sayfa tanısını kopyala"** düğmesi vardır. Düğme, açık UYAP
sekmesindeki yapı özetini panoya koyar: çerçeve sayısı, tablo/satır sayıları, enjekte edilen düğme sayısı,
esas numarası bağlamı var mı ve evrak bağlantılarının **rakamları maskelenmiş yol biçimleri**. Hiçbir
metin, isim, dosya numarası, bağlantı değeri ya da anahtar içermez (testle doğrulanır). Avukat bu çıktıyı
gönderirse `content.js` içindeki `ROW_SELECTOR` ve `DOC_RE` gerçek sayfaya göre ayarlanabilir.

## Gerçek hesapla doğrulama listesi (avukat bir kullanıcıyla)

1. Eklentiyi kur, API adresini ve anahtarı gir, "Bağlantıyı dene" → "hazır ✓".
2. UYAP Avukat Portalı'nda bir dosyanın evrak listesini aç. Her evrak satırında bir düğme ve listenin
   üstünde araç çubuğu görünmeli; giriş ve ana sayfada görünmemeli.
3. Düğme sayısı yanlışsa "Sayfa tanısını kopyala" çıktısını gönder.
4. Bir PDF ve bir UDF evrakı aktar; NHR Hukuk'ta dava belgeleri arasında görünmeli, "Belgelerle Sor"
   sekmesinde içerikten soru sorulabilmeli (UDF metni okunmalı).
5. Taranmış bir evrakta "OCR ile okundu" rozeti çıkmalı.
6. Otomatik aktarım kapalıyken hiçbir evrak kendiliğinden gitmemeli.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_office_public.py tests/test_udf.py -q

# Gerçek Chromium + sahte UYAP (yerel HTTPS, *.uyap.gov.tr yerel sunucuya yönlendirilir; ağ yok):
$env:NHR_BROWSER_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_uyap_extension_browser.py -q
```

Tarayıcı testleri eklentinin mantığını (yanlış düğme, onay, otomatik aktarım kapısı, ayar penceresi)
doğrular. `NHR_EXTENSION_DIR` ile eski bir sürüm aynı testlerle sınanabilir; git'teki önceki sürümde
10 testten 8'i başarısız olur.

## Gerçek UYAP'ta ilk temasta bulunan hata (2026-10-01, v2.8.1 ile düzeltildi)

Otomatik aktarım açıkken Vatandaş Portalı "Dosya Sorgulama" ekranında dava satırlarına tıklayınca eklenti
sayfadaki **tüm** bağlantıları taradı. Sayfada duran herkese açık e-Devlet kılavuz PDF'i ve bir örnek UDF
dava evrakı sanıldı ve dava satırının adıyla 22 kez gönderildi (içerik özeti: yalnız iki farklı dosya).
Kişisel belge gitmedi, ama dava adları ve sahte kayıtlar geldi. Düzeltmeler:

- Yalnız UYAP'ın kendi alan adındaki (`*.uyap.gov.tr`, `*.adalet.gov.tr`) bağlantılar evrak sayılır; kılavuz,
  yardım, örnek ve sözleşme bağlantıları ile menü/üst-alt bilgi/yan panel alanları dışarıda kalır.
- Arka plan betiği UYAP dışı adresten belge indirmez (savunma katmanı).
- Otomatik aktarımda aynı içerik (SHA-256) oturumda bir kez gönderilir; elle gönderim engellenmez.
- Dosya künyesi artık yalnız esas numarası belli ve indirilmeye çalışılmış evrakı olan dosyada gönderilir.
- Regresyon testleri: gerçek ekranın benzeri sahte sayfa (`/vatandas/dosya-sorgulama`), eski sürümde başarısız.

**Bulunan yapı:** Vatandaş Portalı'nda dosya penceresinin "Evrak" sekmesi tablo değil **klasör ağacıdır**
("Dosyaya Eklenen Son 20 Evrak", "Tüm Evraklar → <esas no> (Ceza Dava Dosyası)"; klasörler kapalıdır, evraklar
açılınca yüklenir; "Ön İzlemeyi Aktifleştir" düğmesi var). Eklentinin satır/bağlantı varsayımı bu yapıda evrak
bulamaz. v2.8.2 tanı çıktısı artık açık pencerenin yapı iskeletini (etiket, sınıf, öznitelik adları, ağaç
düğümü örnekleri, düğme/sekme etiketleri) verir; metin, ad ve değer içermez (testle doğrulanır). Ağaç yapraklarını
açıp indirme yolunu bulmak için bu çıktı gerekir.

**Tanı dosyası ve tıklama kaydı (v2.9.0):** pano yerine dosya kullanılır. "Sayfa tanısını kopyala" aynı çıktıyı
`İndirilenler\NHR-Hukuk-UYAP\tani-<zaman>.json` olarak da yazar. "Tıklama kaydını başlat (60 sn)" süre boyunca
tıklamaları, sayfanın yaptığı ağ isteklerini (yalnız yol biçimi), eklenen iframe/dialog öğelerini, indirmeleri ve
açılan yeni sekmeleri kaydeder ve `tani-kayit-<zaman>.json` yazar. Bu, "evrak yaprağına tıklayınca ne oluyor?"
sorusunu kullanıcıya tarif ettirmeden yanıtlar. Hiçbir metin, ad, öznitelik değeri, rakam ya da sorgu değeri
kaydedilmez (tarayıcı testiyle doğrulanır). Eklentiye yeni izin eklenmedi.

Yine de gerçek evrak listesi sayfasında seçicilerin tutup tutmadığı doğrulanmadı: "Sayfa tanısını kopyala"
çıktısı bekleniyor. Sunucuda içerik özetiyle yinelenen denetimi henüz yok.

## Evrakları klasör yapısıyla çekme (v2.11.0)

**Gerçek Vatandaş Portalı'nda ölçülen akış** (tıklama + tarayıcı düzeyi ağ kaydı, 2026-10-02):

- Dosya penceresinin "Evrak" sekmesi bir **klasör ağacıdır** (jQuery treeview): `li.expandable/collapsable`,
  klasör `span.folder`, evrak `span.file[evrak_id]` (eki olan evrakta çocuk yaprak `ana_evrak_id` taşır).
  Yapı: dosya → "Dosyaya Eklenen Son 20 Evrak" (kısayol, aynı evraklar) ve "Tüm Evraklar → <esas no> (… Dava Dosyası)
  → <evrak türü> (<adet>) → evrak → ek".
- Yaprağa tıklamak **ön izleme açıkken** (`onIzlemeDurumu` düğmesi "Ön İzlemeyi Aktifleştir") şunları tetikler:
  `POST dosya_evrak_turu_brd.ajx` (`evrakId`), ön izleme iframe'i `viewer.jsp?mimeType&evrakId&dosyaId&yargiTuru`, ve iframe
  içinden **`GET view_document_brd.uyap?mimeType&evrakId&dosyaId&yargiTuru`** → `200`, `application/vnd.oasis.opendocument.text`
  (**ODT**), `attachment`. Belge bu adresten kullanıcının kendi oturumuyla gelir.

**Eklentideki akış** (popup → "Bu dosyadan evrak seç → …"; yalnız düğmeye basılınca, otomatik
aktarım ayarından bağımsız): bağlantı anahtarı denetlenir → ön izleme kapalıysa açılır (açıksa dokunulmaz) → klasörler
açılır (yapraklara tıklanmaz) → evraklar klasör yoluyla listelenir, "Son 20" kopyaları `evrak_id` ile elenir →
**onay penceresi** (evrak sayısı, dosya, müvekkil verisi uyarısı) → her evrak için yaprağa tıklanır, UYAP'ın `view_document_*`
isteğinin adresi arka planda **yakalanır** (yalnız bellekte, kaydedilmez), belge bu adresten indirilip yüklenir, en az 1,5 sn
aralıkla. **Evrak sayısı sınırı yoktur** (kullanıcı istediği kadar seçip çekebilir); korumalar hız (evrak başına birkaç sn), ardışık 3 hatada
durma ve "Çekmeyi durdur"dur. Aynı içerik bir çekmede bir kez gönderilir.

Sunucu: ODT kabul edilir ve okunur (UDF gibi `content.xml`); `klasorYolu` alanı `office_case_documents.uyap_path` sütununa
yazılır (migration 036), dava sayfasında evrakın altında "📁 yol" olarak görünür. Henüz klasör **ağacı** görünümü yok,
yol metin olarak gösterilir.

**Bilgisayara klasör olarak indirme (v2.12.0):** popup'taki "Bu dosyayı klasör olarak bilgisayarıma indir" aynı akışı JurisAI'ya
bağlanmadan çalıştırır (bağlantı anahtarı gerekmez) ve evrakları `İndirilenler\JurisAI-UYAP\<esas no + mahkeme>\<UYAP klasörleri>\<evrak>`
yoluna yazar; dosya sistemi için yasak karakterler ve `..` temizlenir, aynı adlı evrak "(1)" soneki alır. Gerçek portalda
(2026-10-02) 4 evrak UYAP'tan alınıp JurisAI'ya klasör yoluyla yüklendi ve metinleri okundu; ek evraklar ("Ek 1") henüz alınmıyor.

**Evrak seçimi (v2.13.0):** çekme artık "hepsini çek" değildir, **kullanıcı seçer**. Dosya listesindeki her satırda
"JurisAI: evrakları seç ve çek" düğmesi çıkar (ya da dosya penceresi açıkken eklenti penceresindeki düğmeler): dosya açılır,
Evrak sekmesine geçilir, ağaç açılır ve **seçim penceresi** gelir: evraklar klasörlerine göre gruplanmış, onay kutulu
(klasör kutusu içindekileri toplu işaretler, "Tümünü seç / kaldır"). Altta üç eylem: "Seçilenleri bilgisayarıma indir",
"Seçilenleri JurisAI'ya aktar", "İptal". Yalnız işaretlenenler istenir; bağlantı anahtarı denetimi seçimden sonra ve
yalnız JurisAI'ya aktarırken yapılır. Eklenti hiçbir zaman tüm dosyaları kendiliğinden çekmez.

**Büyük dosyada bulunan hatalar (2026-10-02, v2.15.0):** 40 evraklı bir dosyada (28 aktarıldı, 12 "aynı içerik atlandı") şunlar görüldü ve
düzeltildi: (1) önizleme ilk istekten ~2 sn sonra aynı belgeyi bir kez daha ister; bu gecikmiş istek sonraki yaprağın adresi sanılıyor,
doğru evrak indirilmiyordu. Eşleştirme artık önizleme sayfasının (`viewer.jsp`) kendi `evrakId`siyle yapılır; yalnız o kimlikle gelen
belge istekleri o yaprağa aittir. (2) Önizlenemeyen evrakta (TIFF) `view_document_brd.uyap` belge yerine kısa bir düz metin döndürür
("Bu evrak türü (Tiff) görüntülenemediğinden dolayı evrak indiriliyor") ve gerçek dosyayı ayrı bir `attachment` isteğiyle indirtir (Chrome
"birden çok dosya indirme" izni de bundan sorar; **Engelle** denebilir, eklenti dosyayı kendisi alır). Metin artık belge olarak kaydedilmez, ayrı
indirme adresi (Content-Disposition: attachment / image/tiff) denenir ve dosya adı uzantısı oradan alınır. (3) Ek evrakın türü artık "Ek"
(önceden bağlı olduğu evrakın başlığı yazılıyordu).

**Doğrulanmayanlar:** gerçek UYAP'ta uçtan uca çekme (yalnız ölçülen istek biçimi ve sahte portal testi var; UYAP'ın
ek başlık/oturum denetimi yapıp yapmadığı denemeyle görülecek), PDF olarak gelen evrakların `mimeType` davranışı, ekler
(`Ek 1`) için aynı adresin çalışıp çalışmadığı, çok büyük (yüzlerce evraklı) dosyalar, UYAP'ın hızlı isteklere tepkisi.

## Eklentinin kendi kendine güncellenmesi (v2.16.0)

Geliştirme kurulumunda ("Paketlenmemiş öğe yükle" ile **repodaki** `web/public/jurisai-avukat` klasörü) elle ↻ ya da F5 gerekmez:
eklenti her 30 sn'de geliştirme sunucusunun yayınladığı `http://localhost:3000/jurisai-avukat/manifest.json` sürümüne bakar; daha yeniyse
kendini yeniden yükler (`chrome.runtime.reload()`) ve açık UYAP sekmelerine yeni içerik betiğini yerleştirir (eski sürümün ölü düğme ve
panelleri temizlenir). Çekme ya da kayıt sürerken beklenir. Karar `decideUpdate` saf işlevindedir (testli): `none | wait | reload | stale`.

- Eklenti **repodan değil eski bir klasörden** (ör. indirilen zip'in çıkarıldığı yer) yüklüyse yeniden yükleme sürümü değiştirmez; bu durumda
  açılır pencerede kırmızı "eski bir klasörden çalışıyor, şu klasörden yükle" uyarısı çıkar.
- Test ortamında kapatmak için `chrome.storage.local.autoUpdate = false`.
- Bu yalnızca geliştirme kurulumu içindir. Avukatlara dağıtımda otomatik güncelleme **Chrome Web Mağazası** yayınıyla (listelenmemiş de olabilir)
  sağlanır; kendi barındırdığımız bir güncelleme adresi Chrome'da yalnız kurumsal politikayla kurulan eklentilerde çalışır.

## Doğrulanmayanlar ve açık işler

- **Gerçek UYAP sayfa yapısı doğrulanmadı.** Test sayfaları gerçek UYAP'ın DOM'unu kanıtlamaz.
  Gerçek bir Avukat Portalı hesabıyla (avukat bir kullanıcıyla) evrak listesi ve dosya penceresi
  ayrıca denenmelidir; bulunamayan satırlar için `content.js` içindeki `ROW_SELECTOR` ve `DOC_RE`
  gerçek sayfaya göre ayarlanır.
- Eklentiler geliştirici modunda zip ile kurulur; avukatlara dağıtım için Chrome Web Store
  yayını ve izin açıklamaları gerekir.
- UYAP kullanım koşulları ve KVKK (müvekkil verisi, avukatlık sırrı) açısından hukuki görüş alınmalıdır.
- Görüntü dosyaları (tif/jpg/png) ve taranmış PDF'ler OCR ile okunur ([ocr.md](ocr.md)); OCR hata
  yapabilir, belge "OCR ile okundu" diye işaretlenir ve tutar/tarih/numaralar aslından doğrulanmalıdır.
