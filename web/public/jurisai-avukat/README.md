# Juris AI - UYAP Avukat Portalı Aktarımı (Chrome, Manifest V3)

## Kurulum

1. `jurisai-avukat.zip` dosyasını indir ve bir klasöre çıkar.
2. Chrome'da `chrome://extensions` aç → **Geliştirici modu**'nu aç.
3. **Paketlenmemiş öğe yükle** → çıkardığın klasörü seç.
4. Eklenti simgesine tıkla; uygulamadaki **UYAP'a Bağlan** sayfasından aldığın bağlantı
   anahtarını yapıştırıp **Kaydet** ve ardından **Bağlantıyı dene** düğmesine bas.
   JURISAI bağlantı adresi eklentide hazır gelir.

## Kullanım

- UYAP Avukat Portalı'nda oturum aç, dosyanın evrak listesini açığa çıkar.
- Her evrak satırında **Juris AI'ya Aktar** düğmesi görünür; sağ alttaki çubuktan
  **Bu sayfadaki tüm evrakları aktar** ile toplu aktarım yapılır.
- İstekler arasında varsayılan 1,5 saniye gecikme uygulanır (oturum güvenliği).

## Teknik notlar

- Belgeler kullanıcının kendi UYAP oturum çerezleriyle (`credentials: "include"`) indirilir;
  şifre veya e-imza bilgisi hiçbir zaman okunmaz/saklanmaz.
- Yükleme `multipart/form-data`: `file`, `evrakAdi`, `evrakId`, `evrakTuru`, `dosyaEsasNo`, `birim`.
- Sunucu tarafında `.udf` dosyaları (zip + `content.xml`) açılır ve XML etiketleri temizlenerek
  salt metin çıkarılır; metin belge kaydına özet olarak işlenir ve OCR/dilekçe akışında kullanılır.
- KVKK: müvekkil verisi içerdiğinden API'nin yerel ağda çalışması veya TLS üzerinden
  uçtan uca şifreli iletim önerilir.
