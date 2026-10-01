# NHR Hukuk - UYAP Avukat Portalı Aktarımı (Chrome, Manifest V3)

## Kurulum

1. `jurisai-avukat.zip` dosyasını indir ve **kalıcı bir klasöre** çıkar (Chrome eklentiyi bu klasörden
   çalıştırır; silersen ya da taşırsan eklenti kaybolur).
2. Chrome'da `chrome://extensions` aç → **Geliştirici modu**'nu aç.
3. **Paketlenmemiş öğe yükle** → içinde `manifest.json` olan klasörü seç.
4. Eklenti simgesine tıkla; uygulamadaki **UYAP'a Bağlan** sayfasından aldığın bağlantı anahtarını
   yapıştırıp **Kaydet** ve ardından **Bağlantıyı dene** düğmesine bas. API adresi hazır gelir.

Güncellemede zip'i aynı klasörün üzerine çıkarıp `chrome://extensions` içinde eklentiyi yenile (⟳).
"Anahtarı yenile" eski anahtarı iptal eder; yenilersen eklentiye yeni anahtarı yapıştır.

## Kullanım

- UYAP Avukat Portalı'nda oturum aç, bir dosyanın **Evraklar** listesini aç.
- Her evrak satırında **NHR Hukuk'a Aktar** düğmesi görünür. Düğme yalnızca bir dosyanın (esas
  numarası olan) evrak listesinde çıkar; giriş ve ana sayfalarda çıkmaz.
- Sağ alttaki çubuktan **Bu sayfadaki tüm evrakları aktar** ile toplu aktarım yapılır; başlamadan
  önce onay sorulur.
- İstekler arasında varsayılan 1,5 saniye gecikme uygulanır (oturum güvenliği).

## Gizlilik varsayılanları

| Ayar | Varsayılan | Ne yapar |
| --- | --- | --- |
| Otomatik aktarım | **Kapalı** | Açılırsa, UYAP'ta bir dosyayı görüntülediğinde evrakları ve künyeyi (mahkeme, esas no, taraf adı) kendiliğinden gönderir. Açarken bilgilendirme onayı istenir. |
| Belgeleri bilgisayara da kaydet | **Kapalı** | Açılırsa her aktarılan belge `İndirilenler/NHR-Hukuk-UYAP` içine de kaydedilir. |

Ayarlar eklenti penceresindedir. Kapalıyken eklenti, düğmeye basılmadıkça hiçbir şey göndermez; arka
plan betiği de ayar kapalıyken otomatik aktarım isteğini reddeder.

## Teknik notlar

- Belgeler kullanıcının kendi UYAP oturum çerezleriyle (`credentials: "include"`) indirilir;
  şifre veya e-imza bilgisi hiçbir zaman okunmaz/saklanmaz.
- Yükleme `multipart/form-data`: `file`, `evrakAdi`, `evrakId`, `evrakTuru`, `dosyaEsasNo`, `birim`.
  Belge türü ve künye alanları sayfa metninden **tahmindir**.
- Sunucu tarafında `.udf` dosyaları (zip + `content.xml`, metin CDATA içinde) gerçekten ayrıştırılarak
  metin çıkarılır; taranmış PDF ve görüntüler (OCR yok) "aranamaz" diye işaretlenir.
- KVKK: müvekkil verisi içerdiğinden API'nin yerel ağda çalışması veya TLS üzerinden uçtan uca
  şifreli iletim gerekir.
- Testler: `tests/test_uyap_extension_browser.py` (gerçek Chromium, sahte UYAP; `NHR_BROWSER_TESTS=1`).
