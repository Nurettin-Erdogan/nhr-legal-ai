# UYAP Dosya Çekici (Chrome Eklentisi)

UYAP Vatandaş Portalı'nda **açık olan kendi oturumunuzu** kullanarak sayfadaki tüm belgeleri (PDF, DOC/DOCX, XLS/XLSX, ZIP, JPG/PNG, TXT, UDF) bulur, sayfalama varsa sonraki sayfalara geçer ve dosyaları `İndirilenler/UYAP` klasörüne toplu indirir. Şifre, e-imza veya oturum bilgisi hiçbir yere gönderilmez.

## Kurulum

1. `uyap-dosya-cekici` klasörünü bilgisayarına indir/çıkart.
2. Chrome'da `chrome://extensions` adresini aç.
3. Sağ üstten **Geliştirici modu**nu aç.
4. **Sıkıştırılmamış uzantıyı yükle** → bu klasörü seç.
5. Araç çubuğunda beliren **U** simgesini sabitle.

## Kullanım

1. UYAP Vatandaş Portalı'nda oturum aç: https://vatandas.uyap.gov.tr
2. Belgelerin listelendiği ekrana git (örn. Dosyalarım → dosya/evrak ekranı).
3. Eklenti simgesine tıkla, gerekirse klasör/bekleme süresi ayarını kaydet.
4. **Dosyaları Çek**e bas. İlerleme çubuğu, sayaç ve günlük canlı güncellenir.
5. **Dur** ile her an durdurabilir, **İndirmeleri Aç** ile sonuçları görebilirsin.

## Ayarlar

| Ayar                | Açıklama                                                                       |
| ------------------- | ------------------------------------------------------------------------------ |
| İndirme klasörü     | İndirilenler içinde oluşturulacak alt klasör (varsayılan `UYAP`)               |
| API anahtarı        | Opsiyonel; API adresi kullanılıyorsa `Authorization: Bearer` olarak gönderilir |
| API adresi          | Opsiyonel liste uç noktası; `?page=1&limit=50` ile tüm sayfalar gezilir        |
| İstek arası bekleme | Sunucu yükünü azaltan gecikme (varsayılan 700 ms)                              |
| En fazla sayfa      | Sayfalama üst sınırı (varsayılan 50)                                           |

## Teknik notlar

- Manifest V3, service worker (`background.js`), content script (`content.js`), Vanilla JS.
- İndirme `chrome.downloads` API'si ile yapılır; her dosya için 30 saniye timeout ve 2 kez yeniden deneme uygulanır.
- Ayarlar ve son durum `chrome.storage.local` içinde tutulur; popup kapansa bile iş sürer.
- `http://` adresleri karışık içerik hatası vermemesi için `https://`'e yükseltilir.
- Tüm hatalar (HTTP, timeout, bağlantı) günlüğe zaman damgasıyla yazılır.

## Sınırlar

- Yalnızca oturumunda görüntüleyebildiğin belgeler indirilebilir.
- Mobil imza / e-imza gerektiren işlemler tarayıcı oturumundan yapılamaz.
- UYAP bazı belgeleri ancak ekranda açıldığında üretir; o dosyaların ekranını bir kez gezmek gerekir.
