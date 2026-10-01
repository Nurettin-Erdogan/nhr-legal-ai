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

## Gizlilik varsayılanları (Avukat Portalı eklentisi, v2.8.1)

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

Yine de gerçek evrak listesi sayfasında seçicilerin tutup tutmadığı doğrulanmadı: "Sayfa tanısını kopyala"
çıktısı bekleniyor. Sunucuda içerik özetiyle yinelenen denetimi henüz yok.

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
