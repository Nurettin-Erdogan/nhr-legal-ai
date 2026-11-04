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

Eski `uyap-extension` yalnız inceleme amacıyla `docs/legacy-uyap-extension` altında tutulur;
MAIN-world ağ yanıtı dinlediği için indirilebilir paket olarak sunulmaz. Bu sürüm daha önce
kurulduysa Chrome'dan kaldırılmalı ve güncel JurisAI eklentisi yüklenmelidir.

İndirilen zip'ler (`web/public/*.zip`) klasörlerle birebir aynı tutulmalıdır; eklenti değişince zip
yeniden oluşturulur.

## Gizlilik varsayılanları (Avukat Portalı eklentisi)

- **Otomatik aktarım kapalıdır.** Açılırsa (ayar penceresinde, bilgilendirme onayıyla) UYAP'ta bir
  dosya görüntülenince evraklar ve künye (mahkeme, esas no, **taraf adı**) kendiliğinden gönderilir.
  Kapalıyken yalnız düğmeye basılan evrak gider; arka plan betiği de ayar kapalıyken otomatik
  aktarım isteğini reddeder.
- **Yerel kopya kapalıdır.** Açılırsa her belge `İndirilenler/NHR-Hukuk-UYAP` içine de kaydedilir.
- **Toplu aktarım onay ister.**
- **Bağlantı anahtarı değişikliği eklenti penceresinde onay ister.** Anahtar `chrome.storage.local`
  içinde tutulur; Chrome eşitlemesine gönderilmez.
- Düğmeler yalnız esas numarası olan bir dosya sayfasında, tek bir evrak satırında çıkar; giriş ve
  ana sayfalarda çıkmaz.

## Sunucu uçları: güvenlik notları

- Kimliksiz genel uçlar gövdeyi kimlik doğrulamadan önce okuduğundan `/uyap-ingest` gövdesi 100 MB,
  çok parçalı yükleme 51 MB ile sınırlıdır; çok parçalı gövde anahtar doğrulandıktan sonra ayrıştırılır.
- Yinelenen belge denetimi sahip, dosya numarası, UYAP birimi, köken ve evrak kimliği kapsamındadır.
  SHA-256 özeti veya yeniden paketlenmiş ODT/UDF'nin tam metni doğrulanır; yalnız ad/boyut eşitliği
  başka bir evrağı atlamak için yeterli değildir. Aynı evrak kimliği altında değişmiş içerik sessizce
  üzerine yazılmaz. Birimi bilinmeyen evrak, birimi bilinen evrakla birleştirilmez.
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

Bu eski sürümün canlı doğrulama durumu sonraki tarihli bölümlerde güncellenmiştir;
güncel sunucuda içerik özetiyle yinelenen denetimi vardır.

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

## Kişiye özel paket: anahtar zipin içinde (v2.26.46, kullanıcı kararı 2026-11-02)

UYAP sayfasındaki "Eklentiyi indir" düğmesi genel zipi değil `POST /api/uyap-extension/package` yanıtını indirir
([api/uyap_extension_package.py](../api/uyap_extension_package.py)): genel paketin bayt bayt aynısı + o kullanıcının yeni bağlantı anahtarını
taşıyan `jurisai-config.json`. Eklenti açılışta (`applyBundledKey`, background.js) bu dosyayı okuyup anahtarı `chrome.storage.local`'a yazar;
kullanıcı anahtar oluşturmaz, yapıştırmaz, onay penceresi görmez. Aynı anahtar yeniden uygulanmaz (`bundledKeyApplied`), sayfadan sonradan
yazılan yeni anahtar ezilmez.

- Anahtar veritabanında yalnız SHA-256 özetiyle durur; düz değer yalnız indirilen zipte bulunur, denetim kaydına yalnız ilk 9 karakteri yazılır.
- Her indirme önceki etkin anahtarları iptal eder: eski zip kopyaları ve ikinci bilgisayardaki kurulum çalışmaz olur (tek anahtar modeli,
  "Anahtarı yenile" ile aynı). Zip hesabın anahtarını taşıdığı için kimseyle paylaşılmamalıdır.
- Genel zip (`web/public/jurisai-avukat.zip`) anahtar içermez; elle kurulumda eski "bağla" akışı (onay penceresi) çalışmaya devam eder.
- Testler: `tests/test_uyap_extension_package.py` (sunucu), `tests/test_uyap_extension_bundled_key.py` (gerçek Chromium, `NHR_BROWSER_TESTS=1`).

## Ağaç eksik yüklenirse: onarım ve yeniden tarama (v2.19.0)

Canlıda aynı dosya her açılışta farklı sayıda evrak veriyordu (463, sonra 456) ve eksik klasör değişiyordu: "aynı evrak iki klasörde"
açıklaması bunu açıklayamazdı (o sabit olurdu), asıl neden ağacın eksik yüklenmesiydi. Düzeltmeler:

- UYAP'ın sayısı artık ağaçtaki **tüm** sayılı klasörlerden hesaplanır (`folderStats`); hiç evrak bulunamayan klasör toplamdan düşmüyordu.
- `repairTree`: bir klasörde UYAP'ın yazdığından az evrak varsa önce beklenir, sonra klasör kapatılıp yeniden açılır (en çok 3 tur).
- `expandAll` tek duraksamada bırakmaz (iki ardışık duraksama).
- Fark kalırsa seçim penceresi eksik klasörleri adıyla yazar ve **"⟳ Ağacı yeniden tara"** düğmesi çıkar.

## Çekmeyi hızlandırma (v2.20.0)

Evrak başına süre: tıklama + UYAP'ın istek yapmasını bekleme + indirme + yükleme + en az 1,5 sn bekleme. Portal IP başına hız
sınırladığı için bekleme **kısaltılmaz** ve evraklar paralel çekilmez (40. evraktan sonra UYAP kısa mesajlar dönmeye başlamıştı).
Hızlanma, çekilecek evrak sayısını azaltarak sağlanır:

- **Yalnızca asıl evraklar** düğmesi (seçim penceresi): ekleri (Ek 1, Ek 2…) işaretlemeyi kaldırır. 2024/124'te 449 evrakın 353'ü ektir.
- **Zaten aktarılanlara tıklanmaz.** JurisAI'ya aktarmadan önce eklenti `POST /api/public/v1/documents/known` ile (anahtara bağlı,
  yalnız anahtar sahibinin çöpte olmayan belgeleri, aynı esas no) hangi evrak kimliklerinin (kalıcı kimlik: Birim Evrak No / ana_evrak_id + başlık; şifreli `evrak_id` değil) hesapta olduğunu sorar; onları atlar. Uç nokta
  eski sunucuda yoksa ya da hata verirse hepsi çekilir (yalnız hızlandırma). Çöpe atılan belge "var" sayılmaz, yeniden çekilir.
- **Süre ölçümü:** özet satırı evrak başına ortalama yakalama / indirme / yükleme / bekleme sürelerini yazar; ayar tahminle değil
  ölçümle yapılır. Sonuç nesnesinde `timing` ve `summary` alanları da vardır.

## JurisAI içinden yönetim: "UYAP Dosyalarım" (v2.21.0, 1. aşama)

Hedef: avukat UYAP'a girer, **dosya listesini, evrak seçimini ve çekme ilerlemesini JurisAI içinde** görür. Piyasadaki benzer ürünler
(ör. LexPanel) de aynı yapıyı kullanır: web uygulaması komut verir, tarayıcı eklentisi köprü olur, oturum tarayıcıda kalır. UYAP şifresi,
e-imza ya da çerezi JurisAI'ya hiç gelmez; JurisAI sayfası UYAP'a kendi başına erişemez (tarayıcı kaynak politikası), bu yüzden eklenti şarttır.

**Köprü protokolü** (`web/public/jurisai-avukat/bridge.js` ↔ `web/src/lib/uyap-bridge.ts`):

- Sayfa `window.postMessage({ source: "jurisai-web", id, type, payload })` yollar; eklenti aynı pencereye `{ source: "jurisai-extension", id, ... }`
  döner. Yalnız beyaz listedeki komutlar iletilir: `PING`, `LIST_DOSYALAR`, `OPEN_DOSYA`, `SET_KEY` (JurisAI sayfası yeni oluşturduğu bağlantı
  anahtarını eklentiye kendisi yazar, elle yapıştırma gerekmez; yalnız `jsai_` biçimli anahtar kabul edilir).
- `bridge.js` yalnız JurisAI sayfalarında (manifest `content_scripts`, şimdilik `http://localhost:3000`) yüklenir; arka plan betiği gönderenin
  kaynağını ayrıca denetler (`WEB_ORIGINS`). **JurisAI yayına alınınca gerçek alan adı hem `WEB_ORIGINS`'e hem manifest'teki `bridge.js` eşleşmesine eklenmeli.**
- Eklenti yeniden yüklenince (otomatik güncelleme) yetim kalan köprü kopyası `chrome.runtime.id` yokluğunda susar; açık JurisAI sekmelerine yenisi yerleştirilir.

**Akış:** `LIST_DOSYALAR` → arka plan en son kullanılan UYAP sekmesinin üst çerçevesine `JURISAI_LIST_DOSYALAR` gönderir → içerik betiği dosya listesindeki
"Dosya Görüntüle" satırlarını okur (hücre metinleri, esas no, birim, `Toplam N sayfadan M. sayfa`) → liste yalnız JurisAI sayfasında tutulur,
sunucuya gönderilmez. `OPEN_DOSYA` satırı anahtarıyla yeniden bulur (liste değişmişse `stale`), dosyayı açar ve UYAP sekmesini öne getirir; evrak
seçim penceresi şimdilik UYAP sekmesinde çıkar.

Hata kodları: `no_uyap_tab` (UYAP sekmesi yok), `no_list` (sekmede dosya listesi yok), `no_content` (içerik betiği yok: F5), `stale`, `busy`, `timeout` (eklenti yok).

**Gerçek UYAP'ta doğrulanmayanlar:** listenin hücre düzeni (esas no/birim tahmini metin desenlerine dayanır), çok sayfalı listede sayfa değiştirme
(şimdi yalnız görünen sayfa okunur ve diğer sayfalar için uyarı gösterilir), Avukat Portalı'nın dosya listesi. Sonraki aşamalar: evrak ağacını ve seçimi
JurisAI'da göstermek (2), çekmeyi ve ilerlemeyi JurisAI'da yürütmek, dosyaları esas no ile davaya otomatik bağlamak (3).

## Gerçek Vatandaş Portalı'nda ölçülenler (2026-10-04, v2.26.0)

Gerçek portalda eklenti kontrollü bir canlı pencerede çalıştırılıp ölçüldü (yalnız yapı ve sayılar; içerik okunmadı). Bulgular ve ürüne etkileri:

- **Dosya listesi kendiliğinden gelmez.** "Dosya Sorgulama" sayfasında "Yargı Türü" (Ceza, Hukuk, İcra, Adli Tıp, İdari Yargı, Satış Memurluğu,
  Arabuluculuk, Tazminat Komisyonu) seçilip "Dosya Sorgula"ya (`#btnQueryDoc`) basılır; sonuç DataTables tablosudur (`#dosya_listesi_table`, varsayılan
  15 kayıt/sayfa, sayfa boyutu seçeneklerinde "Tümü" = `-1`). Eklenti **her yargı türünü sırayla sorgular**, sayfa boyutunu "Tümü" yapar (yoksa "Sonraki" ile
  gezer) ve tüm dosyaları tek listede döndürür. Sorgunun bittiği, sonuç değişmese de doğru çalışsın diye ağ isteğinin tamamlanmasından (`PerformanceObserver`,
  `vatandas_dosyalari_sorgula.ajx`) anlaşılır (100-400 ms). Örnek hesap: 8 tür, 21 dosya, 13 sn.
- **Dosya Sorgulama sayfasında değilsek** yan menüden açılır: bağlantı `javascript:menuButtonClick("12573")`; yalıtılmış dünyadan tıklamak işlevi çalıştırmaz,
  bu yüzden arka plan betiği işlevi sayfanın kendi dünyasında (`chrome.scripting`, `world: "MAIN"`, yalnız sayısal kimlik) çağırır. Sayfa yenilendiği için yanıt
  `navigating` döner; JurisAI sayfası birkaç sn sonra yeniden dener.
- **`evrak_id` her sayfa yüklemesinde yeniden şifrelenir** (66 karakter; ardışık üç yüklemede tüm kimlikler farklıydı). Eski yaklaşım (kimliğe göre say, kimliğe göre
  "zaten aktarıldı" de) bu yüzden canlıda 445-467 arasında oynayan sayılar veriyor ve hiçbir zaman eşleşemiyordu. **Kalıcı kimlik:** evrak = balondaki
  (`data-original-title`) **"Birim Evrak No"**; ek = üst evrakın düz **`ana_evrak_id`**'si + "Ek N" başlığı; ikisine de dosyanın birimi eklenir
  (`ev:<no>@<birim>`, `ek:<ana>:<başlık>@<birim>`). Şifreli `evrak_id` yalnız bu bilgiler yoksa son çaredir. Sonuç: aynı dosya üç taze yüklemede hep aynı öğeleri verir;
  UYAP'ın klasör sayıları toplamı ile bulunan evrak sayısı birebir tutar (örnek dosya: 98 = 98, 252 ek).
- **Aynı ekler iki evrakın altında görünebilir** (örn. aynı 104 ek hem "Gelen Talimat İsteği Yazısı" hem "Talimat Gönderme Yazısı" altında, aynı `ana_evrak_id`).
  Kalıcı kimlikle bir kez listelenir/çekilir. (İki konumdaki aynı başlıklı ekin baytlarının eşitliği canlıda ayrıca doğrulanamadı: önizleme belge isteği
  iframe içinde ve indirme olarak geldiği için sayfadan ölçülemedi; çekme sırasında içerik özeti zaten aynı belgeyi yakalar.)
- **"Son 20 Evrak"** kısayolundaki öğeler asıl ağaçtakilerle aynı Birim Evrak No'yu taşır; asıl ağaç varken yok sayılır.
- **Modal kapanırken (≈300 ms) gelen "Dosya Görüntüle" tıklaması yutulur** (bootstrap). Bir dosyadan diğerine geçerken kapanıştan sonra beklenir, satır yeniden
  bulunur ve açılmazsa yeniden denenir.
- **UYAP boşta kalan oturumu kapatır** (~15-30 dk). Aktarım sürerken sayfa yeniden yüklenip oturum düşerse iş durumu kaybolur: JurisAI sayfası bunu "UYAP sayfası
  yenilenmiş ya da oturum kapanmış olabilir" diye açıklar. Aynı hesapla başka yerden giriş de oturumu düşürebilir.
- **Gizli sekmede zamanlayıcılar kısılır** (Chrome): UYAP sekmesi arka plandayken bekleme, arka plan betiği üzerinden (`JURISAI_SLEEP`) yapılır.

## JurisAI içinden güvenilir aktarım (v2.26.1)

- Önerilen indirme artık `jurisai-avukat.zip`: JurisAI web köprüsü bu eklentidedir.
  Bağımsız dosya çekici ayrı ve alternatif olarak etiketlenir; aynı köprüye sahip olduğu varsayılmaz.
- Dosya listesinde 2.000 kayıt kesintisi kaldırıldı. Arama tüm alınan liste üzerinde çalışır;
  ekranda 50'şer kayıt gösterilir. Bu yerel sayfalama UYAP'ın tarama sayfalamasından ayrıdır.
- Eklenti tüm tür/sayfaları tamamladığında `complete=true` verir. Tür sorgu hataları, yüklenmeyen
  sonraki sayfa ve 80 sayfalık güvenlik sınırı açıkça raporlanır. Eski/sadece görünür satırları
  okuyan eklenti yanıtı tam liste sayılmaz. Aynı anda listeleme ve ağaç/aktarım başlatılmaz.
- Sayfa açma artık yalnız ilk sayfada dosya aramaz: "Tümü" seçeneği olmayan listede sonraki
  sayfalardaki dosya da bulunur. Değişmeyen/yüklenmeyen sonraki sayfa eksik tarama sayılır.
- Eksik evrak ağacı yeniden taranabilir. Kullanıcı eksik taramayı açıkça kabul etmeden aktarım
  başlatılamaz. 20.000 öğelik ağaç ekranı güvenlik sınırı da sayım uyarısında gösterilir.
  Tek aktarımda 5.000'den fazla seçim sessizce kesilmez: açık hata verilir, parçalı aktarım gerekir.
- Durdurulan/hatalı aktarım yeşil başarı göstermez. "Yeniden tara ve kalanları seç" yeni bir
  ağaç/mevcut-belge kontrolü yapar ve hesapta olanları varsayılan seçimden çıkarır; aktarım için
  yeniden kullanıcı onayı gerekir. Bu kalıcı görev devam ettirme değildir: UYAP sekmesi/oturum
  kapanırsa kullanıcı yeniden giriş yapar. Mevcut-belge sorgusu başarısızsa atlama garanti edilmez.
- Şifre/çerez sunucuya aktarılmaz; dosya listesi tarayıcı belleğinde tutulur. Merkezî hukuk
  korpusu bu akışın parçası değildir. Eklentiye yeni izin eklenmedi.

Apilex'in kamuya açık [platform](https://www.apilex.ai/tr/platform) ve
[eklenti açıklaması](https://chromewebstore.google.com/detail/apilex-ai-for-legal/eifhpjccnfcdaaeomidagonmkllcoogk)
UYAP'tan tarayıcı eklentisiyle proje aktarımını doğrular. Kapalı uygulamasındaki düğmeler,
kalıcı iş kuyruğu ve tekrar deneme davranışı doğrulanmış değildir; bu bölüm Apilex'in iç
uygulamasının birebir kopyası veya onunla performans karşılaştırması değildir.

## Doğrulanmayanlar ve açık işler

### Canlı kontrol ve sekme düzeltmesi (2026-10-04, v2.26.2)

- Vatandaş Portalı hesabında 21 dosya listelendi (2 Ceza, 2 Hukuk, 17 İcra).
  Seçilen dosyanın ağacında 4 asıl evrak ve 1 ek bulundu; klasör sayıları eşleşti.
- Canlı testte evrak taramasında `busy` durumu görüldü. İncelemede `openEvrakTab`
  işlevinin bağlantıdan önce onu saran `li` öğesini seçebildiği bulundu. Artık
  yalnız tıklanabilir bağlantı/düğme/sekme hedeflenir. Test sayfası da olayı
  gerçek Bootstrap davranışına uygun olarak yalnız bağlantıda dinler.
- Sıkılaştırılan sekme testi eski kodda başarısız oldu; düzeltmeden sonra 5 ilgili
  Chromium testi geçti (sekme açma, onay kapısı, ağaç, aktarım ve zaten olanı atlama).
  Bu tek başına canlı aktarım kanıtı değildir: gerçek belge yükleme, içerik/
  üst veri kontrolü ve yinelenen aktarım testi ayrıca tamamlanmalıdır.
- Bu canlı kontrolün sonunda Chrome hâlâ 2.26.1 bildiriyordu ve tarama `busy`
  hatasına dönüyordu. Gerçek evrak aktarımı tamamlanmadı; bu test için eklenen
  belge yok. `busy` durumunun tek nedeni sekme seçimi diye kabul edilmedi.
  2.26.2 kurulumu sonrası canlı tek-belge ve yinelenen aktarım testi tekrar gerekir.

### Toplu çekimde belge yerine dönen yanıtlar (2026-10-05, v2.26.3)

- Gerçek Vatandaş çekiminde (dosya 2020/1204, v2.26.2) 80 evraktan 6'sı hata verdi:
  3'ü "kısa bir metin yanıtı", 2'si "belge yerine sayfa döndü (oturum kapanmış
  olabilir)", 1'i görünmedi. Aynı çekimde 74 evrak geldiği için "oturum kapanmış"
  yanıltıcıydı.
- Hata nedeni UYAP'ın kendi mesajını yeniden taşır (rakamlar `#` ile maskeli, en çok
  120 karakter). HTML yanıtta sayfa başlığı/metni eklenir; "oturum kapanmış olabilir"
  yalnız metin oturum/giriş belirtisi taşıyorsa ya da boşsa yazılır.
- Yeniden deneme artık hata metnindeki bir sözcüğe değil `retryable` bayrağına bağlı:
  kısa metin ve HTML yanıtı, HTTP 429/5xx ve zaman aşımı bir kez 8 sn beklenip
  yeniden denenir. Kapanmış oturumda en kötü ek bekleme, ardışık 5 hata sınırı
  nedeniyle yaklaşık 40 sn'dir.
- **Canlı doğrulanmadı:** bu değişiklik sahte UYAP sayfasında sınandı; 6 evrağın
  gerçek nedeni (yetki, önizleme, oturum) yeni sürümle yeniden çekimde okunacak.

### Güncelleme sonrası tamamlanan canlı tek-belge testi (2026-10-04)

- 2.26.2 uygulama köprüsünde doğrulandı. Yeniden kurulumda eklenti anahtarı
  kaybolmuştu; kullanıcı onayıyla aynı hesap için yenilenip eklentiye bağlandı.
- Kalan `busy` sorunu uygulamanın geliştirme girişindeki React StrictMode'un
  effect'i yeniden kurmasıyla ilişkilendirildi. Eşzamanlı aynı dosya/tür için
  TREE başlatmaları artık tek yanıtı paylaşır; farklı dosyalar birleşmez ve
  biten/başarısız istek sonraki yeniden taramayı engellemez. Regresyon testi
  eski kodda iki istekle başarısız oldu, düzeltmede geçti.
- Canlı akışta 21 dosya listelendi. Seçilen dosya için 4 asıl evrak + 1 ek
  eksiksiz sayıldı. Yalnız onaylanan Dosya Gönderme evrakı aktarıldı.
  9.430 bayt ODT ve 348 karakter metin örneği kaydedildi; metindeki esas
  numarası, mahkeme ve tarih üst verilerle eşleşti. HTML hata sayfası değildi.
- Yeniden taramada evrak `JurisAI'da var` olarak gösterildi ve varsayılan
  seçimden çıktı. Bilinçli tekrar seçiminde 0 aktarım / 1 zaten var sonucu
  görüldü. Sahibe/dosyaya kapsamlanmış salt okunur DB kontrolünde tek kayıt,
  aynı belge kimliği ve aynı SHA-256 korundu.
- Dosyalar ekranında eklentinin `uyap-avukat-eklentisi` kökeni yanlışlıkla
  `Elle` diye gösteriliyordu. Kaydedilen köken değiştirilmeden UYAP rozetiyle
  gösterilir; hem içe aktarma hem eklenti kökeni için regresyon testi eklendi.
- Sonraki bağlantı incelemesinde kurulu 2.26.2 kopyasının dört ana dosyası
  proje kopyasıyla SHA-256 üzerinden aynı bulundu. Sayfanın PING bekleme süresi
  1,5 saniyeden 5 saniyeye çıkarıldı; hata kodu/metni artık gizlenmez ve yanıtsızlık
  kurulumun yokluğu olarak sunulmaz. 1,8 saniyelik geç yanıt ile gerçek hata
  metninin korunması izole testte doğrulandı. Bu düzeltmenin kullanıcının açık
  Chrome oturumunda bağlantıyı giderdiği henüz canlı doğrulanmadı.
- Bu bir **Vatandaş Portalı, tek evrak** canlı testidir: Avukat Portalı,
  bütün dosya türleri, büyük dosyanın bütün ekleri ve toplu yükleme bu testle
  doğrulanmış sayılmaz. Merkezî korpus ve mevcut belgeler değiştirilmedi;
  yeni test evrakı kullanıcı hesabında bırakıldı. Anahtarlar/metin yayımlanmadı.

- **Gerçek Avukat Portalı sayfa yapısı doğrulanmadı.** Yukarıdaki canlı Vatandaş
  Portalı testi Avukat Portalı'nı kapsamaz; test sayfaları da onun DOM'unu kanıtlamaz.
  Gerçek bir Avukat Portalı hesabıyla (avukat bir kullanıcıyla) evrak listesi ve dosya penceresi
  ayrıca denenmelidir; bulunamayan satırlar için `content.js` içindeki `ROW_SELECTOR` ve `DOC_RE`
  gerçek sayfaya göre ayarlanır.
- Eklentiler geliştirici modunda zip ile kurulur; avukatlara dağıtım için Chrome Web Store
  yayını ve izin açıklamaları gerekir.
- UYAP kullanım koşulları ve KVKK (müvekkil verisi, avukatlık sırrı) açısından hukuki görüş alınmalıdır.
- Görüntü dosyaları (tif/jpg/png) ve taranmış PDF'ler OCR ile okunur ([ocr.md](ocr.md)); OCR hata
  yapabilir, belge "OCR ile okundu" diye işaretlenir ve tutar/tarih/numaralar aslından doğrulanmalıdır.

## UYAP → dava → aranabilir belge (2026-10-05)

- Yeni sunucu aktarımında **açıkça gönderilen dosya numarası + birim** birlikte eşleşir.
  Metin içindeki başka dosyaya yapılan atıftan otomatik dava oluşturulmaz. Tek eşleşmede mevcut
  dava/müvekkil kullanılır; eşleşme yoksa `pending` dava oluşturulur, müvekkil ve açık/kapalı durumu
  tahmin edilmez. Birden çok eşleşme ve elle kurulmuş bağlantılar değişmez.
- Mevcut arşiv için UYAP sayfasında **"Mevcut UYAP belgelerini davalara bağla"** düğmesi vardır.
  `POST /api/office/uyap/link-cases` yalnız giriş yapanın aktif, henüz bağlanmamış UYAP belgelerini
  işler; eksik üst veri/belirsizlik ayrı sayılır. 500'lük işlem gruplarında `next_cursor` ile ilerler;
  eşleştirilemeyen ilk grup sonraki belgeleri engellemez. Bu sunucu işlem sınırıdır, ekran sayfalaması değildir.
- Davanın belge listesi tüm sayfaları toplar. Belge olguları da 100'lük API sayfalarını sonuna kadar
  alır; `total` ve `ready` gerçek toplamdır. Tekrar eden/boş eksik sayfa tam başarı diye sunulmaz.
  AI özetinin kaynak/metin bütçeleri kaldırılmamıştır; bütün belgelerin listelenmesi sınırsız model
  bağlamı veya bütün belgelerin aynı yanıtta kullanıldığı anlamına gelmez.
- ZIP eki aslı değiştirilmeden saklanır; desteklenen üyelerin metni `Arşiv eki: <üye yolu>` kaynağıyla
  indekslenir. Diskte açılmaz. Metin çıkarma koruma değerleri (saklamayı sınırlamaz): en çok 2000 üye, toplam 1 GB açılmış veri,
  üye başına 256 MB. Geçersiz yol, sembolik bağ, şifreli/iç içe arşiv, aşırı sıkıştırma, bozuk veya desteklenmeyen
  üye reddedilir. Üyelerden biri okunamazsa kısmi metin `ready` sayılmaz; asıl ZIP indirilebilir kalır.
  RAR ve XLS/XLSX bu değişiklikle aranabilir hâle gelmemiştir.
- Mevcut kurulumda `database/migrations/046_uyap_court_identity.sql` yönetici bağlantısıyla uygulanır;
  yeni kurulum karşılığı `database/init/047_uyap_court_identity.sql`'dir. Yalnız iki mükerrerlik indeksi
  birim kapsamıyla yenilenir; belge/dava silinmez, RLS değişmez. API yeniden başlatılmalıdır.

Doğrulama: `tests/test_uyap_workflow.py` ayrı test veritabanında gerçek `nhr_runtime`/RLS ile çalışır
ve sonunda geri alınır. `tests/test_archive_processing.py`, arayüz belge/olgu sayfalama ve arşiv
mükerrerlik testleri birlikte kullanılmalıdır. Bu kontroller gerçek UYAP oturumundan yeniden aktarım
ve gerçek Avukat Portalı testi yerine geçmez.

## Atomik aktarım ve yayın adayı (2026-10-05, v2.26.10)

- Elle içe aktarma artık `POST /api/office/uyap/import` üzerinden oturumla doğrulanır.
  Dosya boyut sınırı olmadan akışla okunur (2026-10-06'dan beri; aşağıya bak); SHA-256 sunucuda hesaplanır.
  İstemcinin gönderdiği sahip, içerik özeti veya evrak kimliğine güvenilmez. Aktarım kaydı
  verilirse aynı kullanıcıya ait olduğu kontrol edilir. UYAP kökenli satırlar genel
  `case_documents` ekleme/upsert yolundan oluşturulamaz; eski web sürümü yenilenmelidir.
- Aynı sahibin UYAP yazımları dış transaction kilidiyle sıralanır. İki eşzamanlı yükleme
  kontrol/ekleme aralığında mükerrer belge üretemez; ters dava sıralı toplu eşleştirmeler
  kilit döngüsü oluşturmaz. Başka kullanıcıların işlemleri aynı sahip kilidini paylaşmaz.
- Dosya numarasındaki boşluklar normalleştirilir; eski kayıtlar da karşılaştırmada
  normalleştirilir. Kalıcı evrak kimliği bulunan kayıtta görünen adın değişmesi artık
  aynı içeriği yeni sürüm sanmaz. İçerik gerçekten değişirse mevcut evrak korunur ve 409 verilir.
- `known` optimizasyonu **dosya numarası + birim + kullanıcı** kapsamındadır. Birimi
  göndermeyen eski eklenti boş bilinenler listesi alır: başka mahkemenin evrakını yanlış
  atlamak yerine yeniden indirir; sunucu yine mükerrerliği kontrol eder.
- Açıkça atanmış müvekkil ile eşleşen davanın müvekkili çelişirse bağ kurulmaz ve
  `client_conflict` sayılır. Yeni dava oluşturuluyorsa açık belge-müvekkil bağı korunur;
  portal metninden kişi tahmin edilmez.
- ODT elle ve ZIP içinden yüklenebilir. Desteklenmeyen ve boş arşiv üyeleri sessizce
  atılmaz; sonuçta dosya adıyla hata gösterilir. Aynı üyeyi aynı yolda iki kez içeren
  arşiv reddedilir. Takvimde bulunmayan tarihler üst veriye yazılmaz; ISO tarihleri korunur.
- Bu adım yeni migration gerektirmez; önceki dava kimliği işi için 046 migrationı
  gereklidir. Eklenti paketleri kaynakla birlikte 2.26.10 olarak yeniden üretildi.
  API, web ve eklenti beraber güncellenmelidir. Yeni izin eklenmedi.

Test kanıtı, kurulum sırası ve tamamlanmadan yayın onayı verilemeyen canlı kontroller
[UYAP yayın kontrol listesinde](uyap-release-checklist.md) ayrı tutulur. Önceki sürümdeki
canlı tek-evrak testi bu sürümün veya Avukat Portalı'nın kabul testi değildir.

## Tüm dosyaları aktar ve eksiksizlik doğrulaması (2026-10-06)

"UYAP Dosyalarım" bölümündeki **Tüm dosyaları aktar** düğmesi listedeki her dosyanın bütün evraklarını sırayla aktarır
ve her dosya için eksiksizliği **sunucudaki kayıtla** kanıtlar (`web/src/lib/uyap-sync-all.ts`,
`web/src/components/UyapSyncAll.tsx`). Eklentide değişiklik yoktur: mevcut köprü komutları (`LIST_DOSYALAR`, `TREE`,
`PULL_IDS`, `JOB_STATUS`) kullanılır.

**Dosya başına akış:** evrak ağacını oku → JurisAI'da olmayan evrakları çek → ağacı **yeniden oku** → gerekirse tekrarla
(en çok 3 çekim). Aktarım sayacına güvenilmez: "gönderildi" sayılan ama sunucuya yazılmayan evrak (ör. v2.26.10'da
düzeltilen, aynı baytlı eklerin atlanması) ancak ikinci okumada görünür.

Bir dosya yalnız şu koşulların hepsi sağlanınca **eksiksiz** yazılır:

1. UYAP'ın ağaçta yazdığı evrak sayısı bulunanla uyuşur (ya da fark yalnız aynı evrakın birden çok klasörde görünmesidir),
   açılamayan klasör ve kimliksiz evrak yoktur;
2. ağaçtaki her evrak kimliği JurisAI'da kayıtlıdır;
3. sunucu kayıtlarını gerçekten bildirmiştir (`knownChecked`).

Aksi hâlde dosya **eksik** (nedenleriyle), ağaç hiç okunamadıysa **okunamadı** yazılır. Oturum/sekme kaybı ya da üst üste
üç dosyanın okunamaması koşuyu durdurur; kalan dosyalar "işlenmedi" kalır. Koşu yeniden başlatılınca zaten aktarılmış
evraklar atlanır; "Eksik kalan N dosyayı yeniden dene" yalnız tamamlanmayanları işler. **Yalnız denetle (aktarmadan)**
hiçbir evrak aktarmadan aynı karşılaştırmayı yapar.

"Bütün dosyalar eksiksiz" bandı ancak her dosya eksiksizse, koşu durdurulmadıysa **ve** dosya listesinin kendisi tam
tarandıysa (`liste.complete`) yeşil olur.

**Sunucu kaydı** (`api/uyap_sync.py`, migration `048_uyap_case_sync.sql`): koşu bitince dosya başına sonuç
`POST /api/office/uyap/sync-report` ile `office_uyap_case_sync` tablosuna yazılır (dosya başına tek satır; RLS: yalnız
sahibi). Sunucu UYAP'ı göremediği için bildirilen "eksiksiz"e körü körüne güvenmez: o dosyanın kendi veritabanındaki
UYAP evraklarını sayar ve sayı ağaçta bulunandan azsa kaydı eksik yazar. Dava, evrak aktarımıyla aynı kimlikle bulunur
(esas no + dosya penceresinin yazdığı birim); aynı kimlikte birden çok dava varsa yazılmaz. UYAP listesindeki üst veri
(yargı türü, dosya türü, durum, taraf rolü, açılış) aynı satıra **UYAP'ın gösterdiği metin olarak** yazılır, yorumlanmaz.
`GET /api/office/uyap/sync-status` son doğrulamaları döndürür; İcra Takibi listesi (`/api/office/execution/files`)
dosya durumunu ve doğrulamayı buradan gösterir.

**Uzun koşular:** iş durumu yoklaması tarayıcı çalışanındaki zamanlayıcıyla yapılır (`web/src/lib/steady-timer.ts`);
JurisAI sekmesi arka planda kalsa da yoklama dakikada bire düşmez. Sayfa görünürken ekranın kapanması önlenmeye
çalışılır. Sayfa kapatılırsa koşu yarıda kalır (uyarı gösterilir), yeniden başlatılınca kaldığı yerden sürer.

Bilinen davranış: çöp kutusuna taşınmış bir UYAP evrakı "kayıtlı" sayılmaz; "Tüm dosyaları aktar" onu yeniden getirir.

### İşletim notu: aynı IP'den toplu istek UYAP'ı kapatır (ölçüldü: 2026-10-06)

Bu bilgisayarda çalışan yerel karar toplayıcısı (`scripts/collect_bedesten.py`, ~600 istek/saat,
`bedesten.adalet.gov.tr`) saatler sonra bağlantı zaman aşımı almaya başladı; **aynı dakikalarda** `vatandas.uyap.gov.tr`,
`turkiye.gov.tr` ve `mevzuat.gov.tr` de bu makineden açılmadı (DNS çözülüyor, TCP 443 kurulmuyor; diğer siteler açık).
Kesintiler toplayıcının hata saatleriyle birebir örtüştü (13:14–13:28, 13:33–13:55, 14:06→). Nedeni kesin değil (hız
sınırı ya da ağın çıkış IP'si), ama sonuç açık: **kullanıcının UYAP'a girdiği bilgisayardan/IP'den adalet.gov.tr'ye toplu
istek atan iş çalıştırılmaz.** Toplama ayrı IP'de (Azure) sürer.

Testler: `web/tests/uyap-sync-all.test.mjs`, `tests/test_uyap_sync.py`; uçtan uca (gerçek eklenti + gerçek sayfa + gerçek
API ↔ sahte UYAP): `.local/e2e_uyap_sync_all.py`.

### Gerçek hesapta ölçülen sonuç (2026-10-06, vatandaş hesabı, eklenti 2.26.11)

21 dosya (2 Ceza, 2 Hukuk, 17 İcra; liste tam tarandı). Önce **yalnız denetle**: UYAP ağaçlarında 1375 evrak, JurisAI'da
1306; 69 eksik (12 dosyada). Sonra gerçek aktarım (700 sn): **1373 / 1375 evrak kayıtlı, 19 dosya eksiksiz**, 67 evrak
gönderildi. Kalan 3 durum:

* **2010/8096 ve 2009/17135** (kapatılmış eski icra daireleri): UYAP "dosyaya ait evrak bilgisi bulunamadı" diyor. Bu bir
  hata değil, UYAP'ın evrak göstermediği dosyadır; orkestratör bunları **evrak yok** (`empty`) sayar (ikinci okumayla
  doğrulayarak) ve eksik/hata saymaz. Yalnız evraksız dosyalardan oluşan koşu "bütün dosyalar eksiksiz" bandını yeşertmez.
* **2024/124 (Ağır Ceza), 2 ek eksik**: iki büyük `.zip` eki. UYAP bunları ön izlemede vermez, yalnız "Kaydet" adresinden
  parça parça (chunked, boyut başlığı yok) verir; ilk bayt 10–18 sn sonra gelir. Ölçülen: biri tam bir zip (33 üye),
  **53,2 MB**, 59 sn'de indi → JurisAI'nın **50 MB sınırını aşıyor**, aktarılamaz. Diğerinde UYAP akışı yarıda kesti
  (12 MB'tan sonra) ve sonraki denemede oturum zaman aşımı sayfası döndü.

**v2.26.12 ile düzeltilenler** (bu ölçümden çıkan eklenti hataları):

1. İndirme zaman aşımı toplam süre değil **"veri gelmedi" süresiydi ama toplam olarak kurulmuştu** (45 sn): yavaş ama akan
   büyük ek 45. saniyede kesiliyordu. Artık her veri parçasında yeniden kurulur; toplam üst süre 10 dk.
2. 50 MB üstü ek, "önizlemede vermiyor; **indirip JurisAI'a yükleyin**" diye raporlanıyordu (elle yükleme de 50 MB ile sınırlıydı,
   yanlış yönlendirmeydi). Sınırın kendisi sonradan kaldırıldı (aşağıya bak).
3. UYAP'ın akışı yarıda kesmesi (`TypeError`) "UYAP indirmeyi yarıda kesti (N MB geldi)" diye adlandırılır; "Kaydet" akışı
   kesilirse bir kez beklenip yeniden denenir.

Testler (gerçek Chromium + sahte UYAP): `test_a_slow_but_steady_save_download_is_not_cut_by_the_no_data_timeout`,
`test_a_save_download_that_uyap_cuts_off_says_so` (50 MB üstü eke ilişkin düzeltme aşağıdaki "Boyut sınırı kaldırıldı"
bölümüyle geçersiz kılındı).

### Boyut sınırı kaldırıldı (2026-10-06, kullanıcı kararı: "hiçbir sınır koyma", v2.26.13)

Yukarıdaki 53 MB'lık ek, 50 MB sınırı yüzünden alınamıyordu. Karar: UYAP evrakı ve dava belgesi yüklemelerinde **boyut sınırı
yoktur**. Bunu güvenle mümkün kılan değişiklikler:

* **Eklenti:** indirilen parçalar bellekte biriktirilmez; her ~8 MB'ta tarayıcının Blob deposuna katılır (büyük ek diske taşar) ve
  JurisAI'a aynı Blob'dan yüklenir. Toplam indirme üst süresi 2 saattir (güvenlik ağı); asıl zaman aşımı "veri gelmedi" süresidir.
* **Sunucu** (`api/upload_stream.py`): çok parçalı gövde Starlette'in geçici dosyasında kalır (1 MB üstü diskte); dosya bir kez
  okunup boyutu/SHA-256'sı hesaplanır, kopyalama dosyadan dosyaya akar. Sunucu belleği dosya boyutuyla büyümez. Kayıt işlemi dosya
  yazıldıktan sonra açılır (büyük kopya sürerken dava satırı kilitli kalmaz). Diskte yer kalmazsa 507/503 ve açık mesaj döner.
  Kimlik doğrulaması gövdeden **önce** yapıldığı için sınırsız gövde yalnız doğrulanmış kullanıcıdan kabul edilir. Eski
  JSON/base64 aktarım ucu (anahtar gövdenin içinde, kimliksiz okunur) 50 MB'lık tavanını korur; eklenti artık onu kullanmaz.
* **İsteğe bağlı işletmeci sınırı:** `MAX_UPLOAD_BYTES` ortam değişkeni ayarlanırsa o üst sınır uygulanır; varsayılan kapalıdır
  (`.env.example`).
* **Aranabilir yapma (indeksleme) ayrı bir adımdır** ve sunucuyu korumak için yüksek tavanları vardır: dosya 512 MB'a, ZIP içeriği
  1 GB açılmış veriye / üye başına 256 MB / 2000 üyeye kadar metne çevrilir. Aşan dosya **yine saklanır ve indirilebilir**,
  yalnız "boyutu nedeniyle metni okunup aranabilir yapılmadı" diye işaretlenir (aranabilir sanılmaz).
* **Web:** sürükle-bırak/seçim ve dava evrakı yüklemesindeki 50 MB denetimleri kalktı; tarayıcıda arşiv açarken bellek yetmezse
  açıklayıcı hata gösterilir.
* **Dosya türleri:** UYAP ekinde gelebilen ses/görüntü kaydı, imza, ofis ve arşiv türleri (mp3, mp4, wav, avi, mov, p7s, 7z, rtf,
  pptx, csv, eml…) kabul listesine eklendi (eklenti ↔ sunucu ↔ web aynı liste; yalnız saklanır, çalıştırılmaz). Çalıştırılabilir
  dosyalar (`.exe` vb.) hâlâ reddedilir.

Dokunulmayanlar (ayrı özellikler): proje belgeleri yüklemesi (`MAX_DOCUMENT_SIZE_MB`, varsayılan 10) ve ana sayfadaki metin
çıkarıcının 10 MB'ı.

Testler: `tests/test_upload_stream.py`, `test_upload_has_no_size_cap_by_default_and_never_holds_the_body_in_memory`,
`test_a_large_upload_is_stored_from_its_temporary_file_and_retries_do_not_duplicate_it` (DB) ve gerçek Chromium'da
`test_an_attachment_over_50_mb_is_uploaded_whole_there_is_no_size_cap`.

### Kalıcı evrak kimliği düzeltmesi (2026-10-06, v2.26.14)

Canlıda ikinci bir doğrulamada, daha önce "eksiksiz" çıkan 4 dosyada 10 evrak yeniden "eksik" göründü. Neden: bazı evraklarda (örneğin
**Kapalı E-Tebliğ Mazbatası**) balondaki "Birim Evrak No" **boştur**; kimlik şifreli `evrak_id`'ye düşüyordu ve UYAP bunu her
oturumda değiştirir. Sonuç: aynı evrak her yeni oturumda "eksik" görünüyor ve her aktarımda **yeniden (çoğaltılarak)** yükleniyordu.

Düzeltme (`content.js` `stableEvrakId`): numarası boş evrakın kimliği, balondaki öteki alanların (onay/gönderim tarihi, kişi, gönderen
dosya no/sayı, açıklama, tür, tip) ve başlığın özetidir (`nn:<24 hane>`); birebir aynı iki evrak ağaç sırasıyla `#0`, `#1` alır, "Son 20"
kopyaları sayılmaz. Hiçbir kalıcı bilgi yoksa şifreli kimlik **son çare** kalır ama `unstableId` olarak sayılır ve dosya "eksiksiz"
yazılmaz ("N evrakın kalıcı kimliği çıkarılamadı"). Testler: `test_evraks_with_an_empty_birim_evrak_no_get_a_stable_identity_that_survives_reloads`,
`test_an_evrak_with_no_stable_identity_at_all_is_counted_so_the_tree_cannot_be_called_complete`.

Not: bu düzeltmeden ÖNCE aktarılan numarasız evraklar sunucuda eski (oturuma bağlı) kimlikle durur; yeniden aktarımda yeni kimlikle ikinci bir
kopya oluşur. Eski kopyalar tek tek içerik özetiyle eşleştirilip çöpe taşınabilir (geri alınabilir); otomatik silinmez.

### Evrak dışı dosya bilgileri: taraflar, safahat, dosya hesabı, tahsilat/reddiyat (2026-10-06, v2.26.14)

Gerçek portalda dosya penceresinin sekmeleri ölçüldü (yalnız yapı; değerler yazılmadı). Dosya türüne göre değişir:

| Dosya türü | Sekmeler |
| --- | --- |
| İcra dosyası (icra dairesi) | Dosya Bilgileri, **Dosya Hesabı**, Taraf Bilgileri, Evrak, Safahat, Evrak Gönderme, Ödeme, Tah./Red. Bilgileri |
| İcra hukuk mahkemesi | Dosya Bilgileri, Taraf Bilgileri, Evrak, Safahat, Evrak Gönderme, Ödeme, Tah./Red. Bilgileri |
| Hukuk (BAM) | Dosya Bilgileri, Taraf Bilgileri, Evrak, Evrak Gönderme, Ödeme, Tah./Red. Bilgileri |
| Ceza (ağır ceza) | Taraf Bilgileri, Evrak, Safahat, Evrak Gönderme, Ödeme, Tah./Red. Bilgileri |
| Ceza (BAM ceza dairesi) | Taraf Bilgileri, Evrak, Evrak Gönderme, Ödeme, Tah./Red. Bilgileri |

Okunanlar (`content.js` `readDosyaDetail`, köprü komutu `DETAIL` → iş türü `detail`): **Dosya Bilgileri** (etiket/değer: Türü, Yolu,
Şekli, Dosya Durumu), **Dosya Hesabı** (Takipte Kesinleşen Miktar, Toplam Faiz, Vekalet Ücreti, Masraf, BSMV, Tahsil Harcı, Toplam Alacak,
Yatan Para, Bakiye Borç), **Taraf Bilgileri** (Rol, Tipi, Adı, Vekil; gizli sütun = iç kimlik okunmaz), **Safahat** (önce salt okunur
"Sorgula" düğmesi: İşlem Yapan Birim, Tarih, İşlem Türü, Açıklama, İşlem Durumu; ölçülen örnek 73 kayıt), **Tah./Red. Bilgileri** (özet
satırı + Tahsilat ve Harç/Masraf tabloları).

* **Hiç dokunulmayanlar:** "Evrak Gönderme" ve "Ödeme" sekmeleri, "Borç Öde" ve "Ekle" düğmeleri, "Detay" düğmeleri. Okuma izin listesiyle
  yapılır (bilinmeyen sekme okunmaz). Sahte sayfada `window.__forbidden` testiyle doğrulanır.
* **Eksiksizlik:** her tablo "Tümü" sayfa boyutuyla ya da sayfa sayfa gezilerek okunur ve UYAP'ın "N Kayıttan" sayısıyla karşılaştırılır;
  tablo AJAX'la dolana kadar beklenir (satır sayısı iki turda değişmeden kalmalı). Sunucu bu karşılaştırmayı **kendisi yeniden yapar**
  (`api/uyap_detail.py`): istemci "tamam" dese de satır sayısı UYAP'ınkine eşit değilse kayıt `complete=false` yazılır. Hiç bilgi sekmesi
  bulunamazsa "okunamadı" (düzen değişmiş olabilir) yazılır, hiçbir şey kaydedilmez.
* **Saklama:** `office_uyap_case_detail` (migration `049`, init `050`): dava başına tek satır, JSONB sekmeler, RLS yalnız sahibi, dava/hesap
  silinince silinir, KVKK dışa aktarımında (`uyap_case_detail`, `uyap_case_sync`; genel CRUD ucuna **açılmaz**, doğrulama sonucu uydurulamasın).
  Dosyanın hiç evrakı yoksa (UYAP "evrak bilgisi bulunamadı" diyen eski icra dosyası) dava kaydı evrak aktarımıyla aynı kuralla açılır.
  Değerler UYAP'ın yazdığı metindir; hiçbir tutar hesaplanmaz, hiçbir hukuki sonuç üretilmez.
* **Uçlar:** `POST /api/office/uyap/case-detail` (oturumlu), `GET /api/office/uyap/case-detail/{case_id}`. İcra Takibi listesi (`/api/office/execution/files`)
  her dosyada UYAP'ın "Dosya Hesabı" alanlarını (Toplam Alacak, Yatan Para, Bakiye Borç) aynen gösterir.
* **Arayüz:** "Tüm dosyaları aktar" her dosyadan sonra dosya bilgilerini okur ve hemen kaydeder (koşu yarıda kalsa da alınanlar kalır);
  rapor "dosya bilgileri: eksiksiz/eksik/okunamadı" yazar. Dava sayfasında yeni **"UYAP Bilgileri"** sekmesi (taraflar, safahat araması,
  hesap, tahsilat) bu veriyi gösterir; eksik okunan her tablo açıkça uyarılır.
* Testler: gerçek Chromium + sahte sekmeli UYAP (`test_the_detail_job_reads_every_read_only_tab_completely_and_never_touches_interactive_ones`,
  `..._pages_through_tables_when_there_is_no_show_all_option`, `test_a_table_that_shows_fewer_rows_than_uyap_declares_is_reported_incomplete`),
  `tests/test_uyap_detail.py`, `web/tests/uyap-detail-view.test.mjs`, `web/tests/uyap-sync-all.test.mjs`.

### Canlı pencere araçları: ölçülen sınırlar (2026-10-06)

* Playwright'ın `--load-extension` ile yüklediği eklenti `chrome.runtime.reload()` ile **yeniden yüklenemez**: eklenti devre dışı kalır
  (`ERR_BLOCKED_BY_CLIENT`). İçerik betiği aynı sürümde ikinci kez çalışmaz (`__jurisaiLoadedVersion`). Eklenti kodu değişince canlı
  pencere yeniden başlatılır ve UYAP'a yeniden giriş gerekir; gerçek kullanıcı Chrome'unda otomatik güncelleme bu sınırdan etkilenmez.
* Eklentinin `host_permissions`'ı yalnız `http://localhost:8766/*` içerir: API adresi `127.0.0.1` verilirse yükleme "Failed to fetch" ile
  düşer (artık "JurisAI sunucusuna ulaşılamadı (adres)" yazılır).

### Geçici okuma hataları ve doğru başarı ölçütü (2026-10-07, v2.26.17)

* Geçici ağaç sorgusu/açma hatası en çok iki kez, 4 ve 8 saniye beklenerek yeniden denenir. Oturum/yetki kaybı veya değişmiş liste
  tekrar edilmez. Zaman aşımı/iptalde eski iş için durdurma komutu gönderilir; üst üste üç kalıcı dosya hatasında koşu yine durur.
* Başka yargı türü sorgulanmadan önce açık dosya penceresi kapatılır. Açılan pencerenin esas no/birim kimliği istenen satırla
  eşleşmeden o pencere kabul edilmez.
* Salt okunur sekmeler `href`, `data-target`, `data-bs-target` veya `aria-controls` ile çözülür; hedef yalnız mevcut dosya
  penceresinde aranır. Sekme/içerik hatası bir kez beklenerek tekrar okunur; DOM'da görünürlük zorla değiştirilmez.
* Yüklenmemiş boş sekme tamam sayılmaz. Safahat sorgusunda eski tablo yeterli değildir: yeni çizim de beklenir. DataTables
  yükleme durumu, satır içeriği ve UYAP toplamı birlikte denetlenir. Durdurma bilgi sekmeleri arasında da uygulanır.
* **Evraklar eksiksiz** rozeti yalnız evrakları anlatır. Genel başarı için dosya bilgilerinin de tam okunup kaydedilmiş olması
  gerekir. Sunucunun eksik dediği bilgi veya evrak raporu istemcide başarıya çevrilmez; kaydetme hatası görünür kalır.
* Yeniden deneme, evrakları tam olsa da bilgileri eksik/kaydedilmemiş dosyaları kapsar. Yeniden denenen alt küme önceki dosya
  sonuçlarıyla birleştirilir; başarılı dosyalar toplam rapordan kaybolmaz.
* Doğrulama/bilgi kayıt istekleri 60 saniyede zaman aşımına uğrar; kayıt onayı alınmadan ikinci koşu başlamaz. Eksik/yanlış
  dosya kimlikli veya bozuk sunucu yanıtı kaydedilmiş sayılmaz. Önceden saklanmış hatalı `complete` bilgisi de tablolardan
  yeniden denetlenerek gösterilir.
* Sorgu formu olmayan eski liste görünümünde bilinmeyen dosya anahtarı doğrudan `stale` döner; açık pencereyi kapatmaya
  çalışıp yanıltıcı `cannot_close` hatasına çevrilmez. Tarayıcı testlerinde başarısız bir testin sekmeleri de temizlenir;
  başka testin oturumu yanlışlıkla seçilmez.

Yerel Chromium testleri gerçek portala istek göndermez; bunların geçmesi canlı UYAP kabul testinin yerine geçmez. Canlı kabul
ölçütü: güncel eklentiyle tam dosya listesi taranmalı, her erişilebilir evrak sunucu kaydıyla eşleşmeli, bilgi sekmeleri eksiksiz
olmalı ve ikinci denetimde gereksiz yeniden yükleme olmamalıdır. Portal/oturum hatası varsa sonuç açıkça eksik kalır.

#### 2026-10-07 test kaydı ve açık kabul kapısı

* API genel yerel testleri: **1.148 geçti, 322 atlandı**. Bu koşuda tarayıcı testleri kapalıydı; izole test veritabanı ve dış
  servis gerektiren işaretli testler de çalıştırılmadı. Atlanan testler geçmiş kabul edilmez.
* Arayüz: **265/265** test geçti; TypeScript kontrolü, değiştirilen UYAP dosyalarının ESLint denetimi ve üretim derlemesi geçti.
  Eklenti ZIP'i kaynak dizinle eşleşti; sunulan son manifest **2.26.17**.
* İlk geniş Chromium koşusu: **95 geçti, 4 başarısız**. İlk hata, sorgu formu olmayan listede geçersiz anahtarın `stale`
  yerine `cannot_close` dönmesiydi. Bu hata sonrasında kapanmayan test sekmeleri başka oturum seçilmesine yol açarak üç testi
  daha etkiledi. Hata yolu düzeltildi; her test sonunda o testin açtığı sekmeleri kapatan izolasyon eklendi.
* Düzeltme sonrası ayrı Chromium grupları: **10/10** (geçersiz anahtar, liste/sayfa, yargı türü, kalıcı kimlik ve modal geçişi),
  **9/9** (etkilenen üç senaryo ve tüm bilgi-sekmesi regresyonları), **3/3** (yanlış modalın reddi, güncelleme ve yeniden enjeksiyon).
  Düzeltme sonrası tüm paketin tek koşuda yeniden geçtiği iddia edilmez. Sahte sayfalar gerçek UYAP'a bağlanmaz.
* Mevcut hesaptaki **1.398** UYAP belgesinin salt okunur kontrolünde eksik fiziksel dosya, boyut/SHA-256 uyuşmazlığı,
  aynı evrak kimliğinde mükerrer kayıt, kimliksiz veya davaya bağlanmamış kayıt bulunmadı. Bu yalnız saklanan belgelerin
  bütünlüğünü gösterir; gerçek UYAP ağacındaki bütün evrakların alındığını kanıtlamaz.
* Canlı Chrome kontrol aracı Windows sandbox başlatma hatasıyla açılamadı; bu çalışmada yeni canlı evrak aktarımı yapılmadı.
  Kullanıcı v2.26.16'yı yüklediğini bildirdi; geniş testteki son düzeltme sonrasında paket v2.26.17 oldu. Canlı kabul için
  son sürüm doğrulanmalı, tam liste/evrak/bilgi denetimi ve ikinci geçişte gereksiz yükleme olmaması ölçülmeli.
* API, web ve korpus paneli sağlık kontrolleri HTTP 200 döndü. `NHR Legal AI PC Collectors` ve
  `NHR Legal AI Azure Corpus Sync` görevleri **Disabled** kaldı; korpus çekimi/embedding yeniden başlatılmadı.

### Kullanıcının başarısız canlı denetim raporu sonrası (2026-10-07, v2.26.18)

Canlı rapor: 21 dosyadan ilk üçü okunamadı, 18'i işlenmedi; evrak ağacı okunamadı, pencere kimliği doğrulanamadı ve
liste değişmiş hataları görüldü. Bu rapor boş dosya veya tamamlanmış aktarım kanıtı değildir. Canlı Chrome kontrol aracı
bu turda da başlatılamadı; aşağıdaki düzeltmeler sentetik portalda doğrulanır, canlı raporun kesin nedeni sayılmaz.

* Evrak sekmesinin yalnız `active` sınıfına güvenilmez: hedef pane görünür olmalı. `Evrak`, `Evraklar`, `Evrak Bilgileri`
  etiketleri izinli; `Evrak Gönderme` yine yasak. İlk tıklama yutulursa salt okunur sekme bir kez daha etkinleştirilir.
  Gizli pane içindeki ağaç hazır sonuç sayılmaz; DOM görünürlüğü zorla değiştirilmez.
* Dosya kimliğinde `.modal-title` içerik başlıklarından önce seçilir. Esas no ve mahkeme eşleşmesi gevşetilmez.
* Başarısız sorgunun yalnız tabloyu temizlemesi başarı sayılmaz: yeni açılabilir satır veya açık boş-sonuç hücresi beklenir.
  Tür sorgusu başarısızsa `query_failed` korunur; yanlışlıkla `stale` denmez, mevcut sınırlı yeniden deneme uygulanabilir.
* Kopyalanan rapor, okunamayan/denenmeyen dosyada yanıltıcı `0/0 evrak` yerine sayının bilinmediğini yazar;
  dosya bilgilerine ait hata nedenlerini de içerir.
* Üç yeni tarayıcı senaryosu eski kodda başarısız oldu (yutulan sekme tıklaması, eski active işareti, içerikte önce gelen başlık).
  Düzeltme sonrası bu senaryolar ve modal/liste/bilgi-sekmesi regresyonları birlikte **10/10 geçti**.
  Tüm tarayıcı paketinin yeniden geçtiği veya canlı UYAP'ın düzeldiği iddia edilmez.
* Ayrı grupta başarısız tür sorgusunun doğru hata koduyla bildirilmesi, tam liste/sayfa taraması ve eşzamanlı listeleme
  izolasyonu **4/4 geçti**. Web testleri **265/265** geçti; paket/kaynak eşleşmesi de bu teste dahil.

### Bilgi sekmeleri: sıfır yükseklik ve doğrulanmış boş tablo (2026-10-07, v2.26.19)

Kullanıcının son canlı denetimi: 21 dosya işlendi, 19 evraklı/2 evraksız dosyada 1.380 evrak kayıtla eşleşti;
yeni evrak gönderilmedi. Dosya bilgileri yalnız 2 dosyada tam, 19 dosyada eksikti. Tekrarlayan uyarılar
`Safahat: sekme açılmadı`, `Dosya Hesabı: sekme açılmadı`; bir dosyada tahsilat tablosu sıfır satırlı ama belirsizdi.

* Sekme açılma denetimindeki `getBoundingClientRect().height > 0` koşulu kaldırıldı: float/absolute çocuklar,
  sıfır yüksekliğe taşan içerik ve `display:contents` gibi düzenlerde açık pane sıfır boyutlu olabilir.
  Yerine pane ve dosya penceresine kadarki bütün üst öğelerin `display`, `visibility`, `hidden` durumu denetlenir.
  Portalın CSS'i değiştirilmez; gizli bir üst öğenin içindeki pane veya `aria-busy` yüklemesi başarı sayılmaz.
* Evrak sekmesinin görünürlük denetimi de aynı kurala alındı. Evrak kimliği/dosya eşleşmesi gevşetilmedi.
* UYAP'ın açık boş-sonuç mesajını taşıyan `td.dataTables_empty`, başka veri satırı ve yükleme yoksa `declared: 0`
  olarak gönderilir. Pozitif kayıt sayısı varsa bu değer korunur; yalnız boş DOM veya belirsiz tablo sıfır kabul edilmez.
  Sunucunun eksiksizlik denetimleri değiştirilmedi.
* Raporda `EVRAKLAR EKSİKSİZ` ile genel başarı ayrıldı; evrakları ve dosya bilgileri birlikte doğrulanıp kaydedilen
  dosya sayısı ayrıca yazılır. Önceki kayıt sayacı, güncel koşu/sonuç varken gösterilmez; gösterildiğinde önceki denetim diye etiketlenir.
* Eski kodda dört yeni Chromium senaryosunun üçü başarısız, yüklemesi süren boş tablo negatif kontrolü başarılıydı.
  İki başarısız test canlı rapordaki aynı sekme-açılmadı uyarılarını üretti; üçüncüsü boş tablo sayısının belirsiz gönderildiğini gösterdi.
  Bu, kod kusurunu kanıtlar; gerçek portalın o andaki DOM'u görülmeden canlı hatanın tek nedeni olduğu iddia edilmez.
* Düzeltme sonrası tek Chromium grubunda **12/12 geçti**: sıfır yükseklik, gizli üst öğe, açık boş sonuç, yüklenen tablo,
  sekme hedefi/yutulan tıklama, bilgi tablosu sayfalama, eksik kayıt sayısı ve evrak sekmesine geçiş regresyonları.
  Bu koşuda diğer 96 tarayıcı testi seçilmedi; tüm tarayıcı paketinin geçtiği söylenmez.
* Web **266/266**, TypeScript/ESLint/sözdizimi ve üretim derlemesi geçti. Genel yerel pytest **1.148 geçti, 331 atlandı**;
  tarayıcı testleri bu genel koşuda kapalı, izole DB ve dış servis gerektiren testler atlandı. İki bağımlılık deprecation uyarısı var.
* Sunulan manifest **2.26.19**, API/web HTTP **200**. Canlı Chrome araçları başlatılamadığı için bu turda canlı belge aktarımı
  veya 21 dosyanın bilgi sekmelerinin tekrar denetimi yapılamadı. Yayına hazır kabulü verilmedi.
* Korpus senkronizasyonu başlatılmadı. Önceden durdurulmuş PC collectors görevi yeniden etkin (`Ready`) bulundu ve önceki durdurma
  talebine göre tekrar `Disabled` yapıldı; Azure corpus sync `Disabled` kaldı. UYAP belgeleri silinmedi/değiştirilmedi.

### Tür tespiti ve statik reddiyat detayı (2026-10-08, v2.26.20)

* Bilinmeyen indirme türü artık PDF varsayılmaz. XML yanıtı XML adıyla,
  ham ZIP ZIP adıyla saklanır; tanınmayan tür `.bin` olur ve desteklenmiyorsa
  sunucu açıkça reddeder. Uzun dosya adlarında uzantı korunur. Küçük içerik
  başlığı XML/PDF ve HTML için kontrol edilir; genel indirme MIME'ı altındaki
  HTML giriş/hata sayfası da belge olarak yüklenmez. HTML makbuz istisnası dar
  alan denetimleriyle korunur.
* Önceden yanlış PDF adıyla saklanan UYAP XML'leri yalnız UYAP kaynağına özel,
  kesin içerik imzasıyla indekslenebilir. Genel yüklemede sahte PDF kabul
  edilmez. Orijinal dosya baytları/adı ve SHA-256 korunur; türetilmiş indeksin
  MIME'ı gerçek türü gösterir.
* XML metni etiket/değer ve nitelik yollarıyla aranabilir. DTD/varlıklar,
  aşırı boyut/derinlik/düğüm/çıktı ve ikili gömülü içerik reddedilir.
  EYP'nin üst yazısı, ekleri ve XML üst verisi okunur; bilinen imza/özet/ilişki
  parçaları hukuk metni sayılmaz. **Elektronik imza doğrulanmış sayılmaz.**
* İç içe ZIP/EYP ortak dosya sayısı, açılmış toplam boyut ve derinlik bütçesiyle
  işlenir. Yol geçişi, sembolik bağlantı, şifreleme ve desteklenmeyen ekler
  reddedilir. Yalnız sıfır bayt `ana_evrak.txt` UYAP yer tutucusu atlanabilir;
  tek başına bu yer tutucusu arşivi aranabilir yapmaz.
* Karma PDF veya çok sayfalı görüntüde bir sayfanın okunamaması artık sessizce
  atlanmaz. OCR hatası/sınırı belgenin tamamını aranabilir ilan ettirmez.
  OCR çıktısı yine hataya açık olarak işaretlenir; eksiksiz indeks, hukuken
  veya karakter karakter doğrulanmış metin anlamına gelmez. Pypdf'nin CFF
  yazı tipi çözümü için `fonttools` bağımlılığı eklendi.
* İndeks önbelleği ayrıştırıcı sürümünü taşır. Eski ayrıştırıcı kaydı, belge
  yeniden indekslenirken yalnız aynı SHA-256'ya dayanarak atlanmaz.
* Varsayılan OCR düzeninin çok kısa/boş sonuç verdiği taramalarda bir kez
  seyrek metin düzeni (`--psm 11`) denenir; aynı sayfanın kalan zaman bütçesi
  kullanılır. Kaynak görüntü değiştirilmez, OCR uyarısı kaldırılmaz. Bu,
  metnin karakter karakter doğruluğuna veya her taramanın okunabileceğine
  ilişkin garanti değildir.
* Gerçek 2020/364 penceresinde statik gizli reddiyat yardımcı tabloları
  gözlendi. Yalnız `tahsilatDetayN` + eşleşen `makbuzDetayGosterN` Detay düğmesi,
  12 sütunlu bilinen şema, kararlı boş tbody ve yükleme olmaması birlikte
  doğrulanırsa sıfır sonuç kabul edilir. `empty_evidence` kayıtla saklanır;
  sunucu da sekme/şema/sıfır koşullarını denetler. Diğer belirsiz boş tablolar
  eksik kalır. Detay/ödeme/evrak gönderme düğmelerine basılmaz; dolu yardımcı
  tablolar korunur ve “Reddiyat detayı” olarak adlandırılır.
* Önceki saklı sayaç “evraklı dosya” diye etiketlenir: 19 evraklı ve iki
  evraksız dosya, toplam 21 dosya eder. Önceki rapor güncel denetim değildir.

Canlı düzeltme ve test kanıtları: [8 Ekim denetim kaydı](uyap-audit-20261008.md).
v2.26.20'nin sentetik testleri, kullanıcı Chrome'unda güncel sürümle yapılacak
son 21 dosyalık kabul denetiminin yerine geçmez.

### Güvenli toparlanma ve tam koşu geçmişi (2026-10-09, v2.26.21)

* `TREE` / `DETAIL` denemeleri artık ilk yanıt veren sekmeye sabitlenir.
  Geçici salt okunur hata devam ederse `RECOVER_READ`, yalnız aynı sekmenin
  son iki dakika içinde hata vermiş aynı işini toparlayabilir. Aktarım işi,
  giriş sayfası, değişmiş dosya kimliği/liste, bilinmeyen iş ve kullanıcı
  iptali otomatik yenileme gerekçesi değildir.
* İçerik betiği aktif iş ve görünür giriş/düzenleme alanı kontrolünden sonra
  yenilemeyi onaylar. Arka plan yalnız doğrulanmış UYAP sekmesini, adresi
  değişmediyse yeniler; yeni URL almaz, giriş yapmaz, ödeme/gönderim işlemi
  çalıştırmaz. Dakikada bir ve toplu koşuda en fazla iki toparlanma vardır.
  Yenileme başarı sayılmaz: aynı dosya tekrar açılıp ağacı yeniden okunur.
* `POST/GET /api/office/uyap/audit-runs`, tüm dosyaları içeren başlangıç ve
  dosya-sonu kontrol noktalarını, ardından değiştirilemez son raporu saklar.
  Evraksız, okunamayan ve işlenmeyen dosyalar da dahil edilir. Kesilmiş koşu
  `finished=false` kalır; hiç okunmayan dosyanın sıfır sayacı "evrak yok"
  anlamına gelmez. Sayaçlar tarihli gözlemdir, bugünkü portal durumu değildir.
* Migration `051_uyap_audit_runs.sql` / sıfır kurulum `052_uyap_audit_runs.sql`:
  kullanıcıya bağlı `office_uyap_audit_runs`; runtime + RLS, uygulamada UUID,
  artan revizyon ve bitmiş kaydı eski kontrol noktasıyla ezmeme koruması.
  Sunucudaki evrak sayısı ve bilgi kaydı bildirilen başarıya ek denetimdir;
  tek başına evrak sayısı aynı kimliklerin eşleştiğinin kanıtı değildir.
* Sadece dosya numarası/birim/yargı türü, sayılar, kısa uyarılar ve bilgi
  sekmelerinin durumları saklanır. Ham liste hücreleri, geçici portal
  anahtarları, bağlantı anahtarı, belge içeriği ve bilgi tabloları saklanmaz.
  Listeleme tek başına rapor göndermez; kullanıcı toplu denetim/aktarım
  başlattığında bu üst veriler kaydedilir. Arayüz bunu açıkça bildirir.
* Son beş koşu eklenti/UYAP oturumu olmadan açılır-kapanır geçmişte okunur.
  API `Cache-Control: no-store` kullanır. Hesap değişince önceki koşu iptal
  edilir; bellek/sürdürme kaydı temizlenir ve eski koşu yeni hesaba yazamaz.
  Geçmiş KVKK dışa aktarmaya, hesap purge akışına ve kullanıcı yedeğine dahil.
  Bu sürüm tarihli raporları otomatik silmez; ticari saklama süresi kararı
  uygulamanın genel veri saklama politikasında ayrıca belirlenmelidir.

9 Ekim v2.26.20 canlı denetimi 21 dosya / 1.382 evrak için başarılıydı.
v2.26.21'in otomatik toparlanması sentetik Chromium'da ayrıca sınandı;
bu, yeni sürümün gerçek portaldaki son kabul koşusunun yerine geçmez.
Test ayrıntıları ve canlı erişim kısıtı [denetim kaydındadır](uyap-audit-20261008.md).

### Son çekim kilidi (2026-10-09, v2.26.22)

Toplu koşu ilk dosyadan itibaren listeyi veren UYAP sekmesine sabitlenir;
sekme kimliği yalnız tarayıcı belleğinde tutulur. Toparlanma onayı ile
yenileme arasındaki kısa kilit sırasında elle çekim, dosya açma ve indirme
probu da reddedilir. Meşgul durumunu sorgulayan güncelleme akışı kilidi görür.
v2.26.21'in tamamlanan 113 testlik Chromium regresyonundan sonra bu dar
güvenlik değişikliği yapıldı; v2.26.22'de ilgili altı Chromium senaryosu
yeniden geçti. Yeni sürümün gerçek portal kabulü henüz tamamlanmadı.

### Ölçüme dayalı aktarım hızlandırması (2026-10-10, v2.26.23)

* Başarılı aktarımda yakalama/indirme/yükleme süresi de iki evrağın
  başlangıçları arasındaki aralığa sayılır; işlem bittikten sonra aynı
  sabit bekleme yeniden eklenmez. Tıklamalı yolun en az 1.500 ms, doğrudan
  yolun en az 500 ms aralığı korunur. Aktarımlar hâlâ sıralıdır. Hata
  sonrası büyüyen bekleme tam uygulanır; son evrakta gereksiz bekleme yoktur.
* Ağaçtaki uygun evrak türüyle eşleşen üç bilinen pasif KEP HTML şablonu
  gerçek belge olarak alınır. Paket/ileti şablonu adres + konu + tarih
  alanlarını gerektirir; alan içermeyen kısa PTT bildiriminde tam metin
  eşleşmesi gerekir. Etkin içerik ve giriş/oturum/yetki/hata belirtileri
  reddedilir; keyfi HTML kabul edilmez. UTF-8 geçerliyse başka kodlamayla
  ikinci kez yorumlanmaz; yalnız geçersiz UTF-8 için Windows-1254 denenir.
  Özgün belge baytları değiştirilmeden yüklenir. Bu şablon tanıma, belgenin
  hukuki doğruluğu veya elektronik imza doğrulaması değildir.
* Yedekteki 105 HTML belge, içerikleri test deposuna kopyalanmadan yerelde
  sınandı: 29 makbuz ve 76 KEP belgesinin tamamı tanındı. Anonim negatif
  örnekler giriş/hata sayfalarının belgeye dönüşmediğini sınar. Gerçek
  Chromium testinde KEP belgesi tek indirme/tek yüklemeyle, baytları
  korunarak aktarıldı; tıklama aralığı ayrıca ölçüldü.
* 100 adet 700 ms'lik doğrudan işlemin deterministik zamanlama modeli,
  eski 120 sn yerine 70 sn hesaplar. **Bu, gerçek UYAP hız ölçümü değildir.**
  UYAP'ın veri göndermeyi durdurduğu büyük ZIP indirmeleri ve bazı dosya
  açma/toparlanma hataları bu değişiklikle çözülmüş sayılmaz. Zaman aşımı,
  dosya kimliği, RLS, aynı evrağı atlama ve son doğrulama korumaları değişmedi.
* 10 Ekim temiz aktarımı 967 belgede eksik bitti; bu hız düzeltmesi o
  koşuyu geriye dönük başarılı yapmaz. Canlı Chrome son kontrolde v2.26.22
  çalıştırıyordu. v2.26.23 ile kalanları çekme ve son tam denetim yapılmadan
  canlı kabul veya yüzde cinsinden hız kazancı ilan edilmez.

### Ek adıyla gelen makbuzlar (2026-10-10, v2.26.24)

Canlı v2.26.23 testinde 2025/197080 dosyasının 15 eksik KEP evrakı
kaydedildi; dosya 108'den 123 belgeye, toplam 967'den 982 belgeye çıktı.
982 belgenin fiziksel bütünlüğü ve hazır indeksleri doğrulandı. Bu, tüm
21 dosyanın yeniden eksiksiz çekildiği veya ölçülmüş bir hız kazancı demek
değildir. Toplu koşu büyük ZIP akışındaki durma ve Ek adlı makbuzların
reddi görüldükten sonra durduruldu; kayıtlı belgeler korunuyor.

v2.26.24, türü tam `Ek` ve adı tam `Ek` / `Ek <sayı>` olan makbuz eklerini
de dar makbuz tanıyıcısına alır. Makbuz başlığı, kurum ve alan eşleşmeleri,
pasif HTML, giriş/hata reddi ve 1 MB sınırı aynen gereklidir. Bilinmeyen
HTML kabul edilmez; belge baytları değiştirilmez. Yetkiler ve ZIP indirme
akışı değişmedi. Yeni paket için 312 Node testi ve seçili 8 Chromium testi
geçti; canlı tarayıcı bağlantısı kesildiğinden makbuz düzeltmesinin son
canlı kabulü bekliyor. Büyük ZIP veri akışı sorunu ayrıca çözülmelidir.

### Kesintili indirme toparlanması (2026-10-10, v2.26.25)

v2.26.24 canlıda beş Ek adlı makbuz ve 38 KEP'i daha aktardı; toplam
1025 belge / hazır indeks fiziksel boyut ve SHA-256 ile doğrulandı.
2024/124 büyük Ek 41 ZIP'i 49,1 MB'dan sonra durdu; 2024/269672'de bir
KEP iletisi yalnız Ek 1 adıyla geldiği için reddedildi. Bu istisnalar
ve kalan dosyalar tamamlanmadan tüm aktarım başarılı sayılmaz.

v2.26.25 önbelleksiz indirir; sıkıştırılmamış Content-Length varsa alınan
baytlarla tutarlılığını denetler. Güçlü ETag bulunan kesik akışlarda en
fazla iki kez Range / If-Range denenir. Devam yanıtı 206 ve aynı güçlü
ETag, URL, MIME, doğru Content-Range/boy ile eşleşmezse birleştirilmez.
ETag olmayan/sıkıştırılmış akışta devam yoktur; sınırlı tam yeniden deneme
korunur. Canlı ZIP'te UYAP'ın Range desteği henüz doğrulanmamıştır.

Yalnız indirme boyunca 20 sn aralıklı yerel Chrome API çağrısı boşta
çalışan kapanma riskini azaltır; iş sonunda temizlenir. Normal 45 sn
ayarında 8 MB geldikten sonra hareketsizlik payı 120 sn olur; ilk yanıt,
küçük evrak, özel kısa ayar ve iki saat toplam sınır korunur. Kontrolsüz
paralellik eklenmez. Ek adlı KEP'ler de yalnız dar metadata ve mevcut
pasif KEP şablonu/alan doğrulamalarını birlikte geçerse kabul edilir.

336 Node ve seçili 11 Chromium testi, typecheck, üretim build'i, sözdizimi ve paket
eşleşmesi geçti. API/arşiv/rapor regresyonunda 30 geçti, 10 DB testi
bağlantı olmadığı için atlandı. Yeni paketin canlı büyük ZIP / Ek 1
kabulü ve 21 dosyanın son tam denetimi bekliyor. Ayrıntılı tarihlenmiş
kanıt ve sınırlamalar: [denetim kaydı](uyap-audit-20261008.md).

### Güncel canlı kabul durumu (2026-10-10 16:15, v2.26.25)

Mevcut 1025 belge silinmeden 356 yeni evrak daha başarıyla aktarıldı.
Son tam **yalnız denetim** 21 dosyanın tamamını okudu: **18 evraklı dosya
eksiksiz, 2 evraksız, 1 evrak eksik, 0 okuma hatası, 0 işlenmeyen**.
**1382 bulunan evrağın 1381'i kayıtlı**; denetimde yeni belge gönderilmedi.
Taraflar/safahat/hesap/tahsilat gibi dosya bilgileri **21/21 eksiksiz
okunup kaydedildi**. RLS kapsamındaki fiziksel dosya, boyut, SHA-256,
UYAP kimliği, dava bağlantısı ve mükerrerlik denetiminde hata yok;
1381 indeks `ready`.

Tek açık aktarım sorunu, 2024/124'ün ilişkili 2022/608 Talimat Dosyasındaki
`Gelen Talimat İsteği Yazısı 28/12/2022 / Ek 41` büyük ZIP'idir. v2.26.25
canlı denemesi 22,5 MB'dan sonra 120 sn veri gelmemesiyle başarısız oldu;
kesik belge kaydedilmedi. Güçlü ETag/Range desteği ve doğal UYAP Kaydet
indirmesinin sonucu henüz doğrulanmadı; kök neden kesin olarak UYAP'a ya
da eklentiye atfedilemez. Daha uzun bekleme/heartbeat değişikliğinin bu
belgeyi çözdüğü iddia edilmez. **Yayın kabulü hâlâ bekliyor.**

Tam izole Chromium regresyonu 121/121, güncel Node regresyonu 348/348,
typecheck ve üretim build'i geçti. Genişletilmiş UYAP/belge/arşiv/içerik
arama Python koşusu 84 geçti, 42 DB testi bağlantı tanımlı olmadığı için
atlandı. Canlı kanıt ve koşu ayrıntıları [denetim kaydındadır](uyap-audit-20261008.md).

### Doğrulama reddi ve canlı indirme ilerlemesi (2026-10-10, v2.26.26)

Dar UYAP `Hata Oluştu / Hata Mesajı / Doğrulama hatası` yanıtı
`UYAP_VALIDATION_FAILED` olarak ayrılır; aynı reddedilmiş adres ve ondan
türetilen Kaydet adresi boşuna tekrar denenmez. Kullanıcıdan dosyayı
yeniden açıp evrakı yeniden seçmesi istenir; bu yanıt tek başına oturum
kapanması diye yorumlanmaz. Hata sayfası makbuz/KEP istisnasıyla alınamaz.

İndirme ilerlemesi alınan/toplam MB, bilinmeyen toplam boyut, son veriden
beri geçen süre ve doğrulanmış sürdürme sayısını gösterir. Yalnız aynı
sekme ve aynı çalışan aktarım işine iletilir; URL, ETag, çerez, bağlantı
anahtarı veya belge içeriği iletilmez. Yeni izin eklenmedi.

**Güncel canlı kabul hâlâ başarısız:** v2.26.26 ile tek eksik Ek 41
19,4 MB'dan sonra 120 sn veri gelmemesiyle durdu; kesik dosya yüklenmedi.
17:12 RLS kontrolünde 1381 kayıt / hazır indeks korundu. Doğal UYAP
Kaydet denemesinde 45 sn içinde tamamlanma olayı alınamadı; bu durum
tek başına doğal indirmenin başarısız olduğunu kanıtlamaz. Kök neden
UYAP, ağ veya eklenti olarak kesinleştirilmedi; yayın kabulü verilmedi.

Yerel doğrulama: 360 Node testi, seçili 9 Chromium regresyonu ve ayrı
bir uçtan uca canlı-iş-ilerlemesi Chromium testi geçti. Son iki sayı tam
Chromium suite'i değildir. Ayrıntılar ve ekran kanıtları
[denetim kaydında](uyap-audit-20261008.md).

### Geçici indirme hatasında taze yakalamaya dönüş (2026-10-10, v2.26.27)

Doğrudan önizlemenin “çok büyük” reddinden sonraki geçici Kaydet kesintisi
artık sarmalayıcı hata mesajı nedeniyle kalıcı evrak reddi sayılmaz.
Worker geçici hata niteliğini korur; içerik betiği bu niteliğe öncelik
vererek bir normal UI tıklamasıyla taze istek yakalar. Taze yakalama
başarısız olursa da geçici hata/backoff niteliği korunur. Kaydet'teki
ikincil kalıcı hata, asıl HTML/giriş sayfası hatasını gizlemez.
Doğrulama reddinde aynı adresin tekrar edilmemesi ve eksik baytların
yüklenmemesi kuralları değişmedi; yeni izin veya uç nokta eklenmedi.

366 Node testi ve yeni tıklama akışı dahil tam **124/124 izole Chromium
testi** geçti (1246,44 sn).

**10 Ekim 20:27 canlı kabul sonucu: başarısız.** Kullanıcının
güncellemesinden sonra v2.26.27 doğrulandı; yalnız eksik Ek 41 aktarıma
seçildi. Yeniden deneme yolu işletildi, üç denemede sırasıyla 18,4 / 28,4 /
33,7 MB geldi; sonuncusu 120 sn yeni veri gelmeyince **0 aktarım / 1 hata**
ile bitti. Toplam boyut bildirilmedi. Mevcut **1381 belge / hazır indeks**
korundu; fiziksel bütünlük ve mükerrerlik kontrollerinde hata yok.
Belge silinmedi, anahtar yenilenmedi. Büyük ZIP'in tamamlandığı, 1382/1382
başarı veya yayın hazırlığı iddia edilmez. Son tam denetim 16:15 tarihli
rapordur; tek evrak denemesi onu yeni tam denetim yapmaz. Kesintinin
UYAP/ağ/eklenti kaynağı henüz kesinleşmedi; yanıt/bağlantı düzeyinde
karşılaştırmalı tanı gerekir. Ekran kanıtı ve ayrıntılar
[denetim kaydında](uyap-audit-20261008.md).

### Etkin isteği durdurma ve iş izolasyonu (2026-10-10, v2.26.28)

“Durdur” artık yalnız sıradaki evrakı engellemez: aynı işin devam eden
UYAP indirmesini, kayıtlı evrak sorgusunu, JurisAI yükleme isteğini ve
yeniden deneme/evraklar arası beklemeyi iptal eder. Kullanıcı iptali
`UYAP_CANCELLED` olarak ayrılır; evrak hatasına veya yeniden denemeye
dönüşmez. Başka sekme, iframe veya eski işin END/CANCEL mesajı aktif
işin iptal denetleyicisini silemez. Aynı anda ikinci aktarım başlatılmaz;
sekme kapanması/gezinmesi sahipsiz ağ isteğini sonlandırır. Yeni izin yok.

Yükleme iptalinden önce sunucu kaydı tamamlamış olabilir; iptal daha önce
kaydedilen belgeyi geri almaz. Sonraki kayıtlı-evrak sorgusu/denetim
gerçek durumu belirler. Kesik indirme yüklenmez ve belge silinmez.

374 Node testi, tip kontrolü, üretim derlemesi, UYAP TypeScript lint'i ve
tam **132/132 Chromium regresyonu** geçti (21 dk 55 sn). Sonradan eklenen
3 sekme/iframe yaşam döngüsü testi ayrıca aynı kaynaklarla geçti: toplam
135 farklı Chromium senaryosu. Ayrı ve geçici PostgreSQL/pgvector test
veritabanındaki genel koşu 1621 geçti; yalnız boş test korpusunda olmayan
bir mevzuat kaydı ile o koşuda opt-in kapalı olan Chromium testleri atlandı.
Chromium yukarıdaki ayrı koşuda çalıştırıldı. Toplam **2130 farklı test
geçti**; bir korpus testi veri olmadığı için atlandı. Web'in sunduğu
v2.26.28 ZIP'inin SHA-256'sı test edilen yerel pakete eşit.

**Bu sürüm büyük Ek 41'in kesilmesini çözdü iddiası taşımaz.** 20:52 RLS
kontrolü hâlâ 1381 kayıt/hazır indeks, 2024/124 için 349 evrak gösteriyor;
fiziksel dosya, boyut, SHA-256, kimlik, dava bağı ve mükerrerlik kontrolleri
hatasız. Son tam canlı denetim 16:15'teki 1382/1381 sonucudur. Canlı
tarayıcı kontrolü kesildiğinden yeni doğal-indirme karşılaştırması
doğrulanamadı; yayın kabulü verilmedi.
