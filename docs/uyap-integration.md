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
