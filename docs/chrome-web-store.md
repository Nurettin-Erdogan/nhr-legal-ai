# Chrome Web Mağazası yayını (JurisAI UYAP eklentisi)

Amaç: avukatlar eklentiyi tek tıkla kursun, güncellemeler kendiliğinden gelsin (elle klasör yükleme ve "paketlenmemiş öğe" biter).
Eklenti **listelenmemiş (unlisted)** yayınlanabilir: mağazada aranmaz, yalnız bağlantıyı bilen kurar; güncelleme ve güvenilirlik aynıdır.

## 1. Başvurudan önce gerekenler

| İş | Kim | Durum |
| --- | --- | --- |
| Chrome Web Mağazası geliştirici hesabı (tek seferlik 5 USD, Google hesabı + 2 adımlı doğrulama) | NHR Yazılım | yapılacak |
| JurisAI'nın **canlı alan adı** (web uygulaması) ve **API adresi** | NHR Yazılım | belirlenecek |
| Gizlilik politikası sayfası canlıda: `web/public/gizlilik-uyap-eklentisi.html` → `https://<alan-adı>/gizlilik-uyap-eklentisi.html` | NHR Yazılım | dosya hazır; `[İLETİŞİM E-POSTASI]` doldurulmalı, **hukuk/KVKK incelemesi** şart |
| Mağaza görselleri (aşağıda) | NHR Yazılım | yapılacak |
| UYAP otomasyonunun UYAP kullanım koşulları ve KVKK açısından hukuki görüşü | NHR Yazılım | yapılacak |

## 2. Paketi üret

```powershell
.\.venv\Scripts\python.exe scripts\build_store_extension.py `
  --web-origin https://<web-alan-adı> `
  --api-url https://<api-alan-adı>/api/public/v1/documents/upload
```

Çıktı `dist/jurisai-avukat-store-<sürüm>.zip` (git'e girmez). Geliştirme paketinden farkları:

- `localhost` adresleri üretim adresleriyle değişir; köprü (`bridge.js`) yalnız `--web-origin` sayfasında yüklenir.
- Kendi kendine güncelleme kapalıdır (`BUILD.store = true`) ve `alarms` izni yoktur: kurulumu Chrome günceller.
- Pakette `localhost` geçen hiçbir metin kalamaz; kalırsa üretim iptal edilir (`tests/test_store_build.py`).

Mağaza ile geliştirme kurulumu aynı anda yüklü olmamalı (aynı komutlara iki kez yanıt verir): geliştirici kendi Chrome'unda birini kaldırır.
Yeni sürüm yayınlamak: `manifest.json` sürümünü artır, paketi yeniden üret, panelde "Yeni sürüm yükle". İnceleme genellikle birkaç saat ile birkaç gün sürer.

## 3. Mağaza kartı

- **Ad:** JurisAI - UYAP Evrak Aktarımı
- **Kısa açıklama (≤132, manifest'teki):** UYAP'ta açtığınız dosyanın evraklarından seçtiklerinizi JurisAI hesabınıza aktarır. UYAP şifreniz size ait kalır.
- **Kategori:** Üretkenlik · **Dil:** Türkçe
- **Ayrıntılı açıklama:**

  > JurisAI UYAP eklentisi, UYAP'a kendi hesabınızla girdikten sonra bir dosyanın evraklarından **sizin seçtiklerinizi** JurisAI hesabınıza aktarır.
  >
  > • Evrakları klasör yapısıyla görür, hangilerini çekeceğinizi siz seçersiniz (ekleri ayrı seçebilirsiniz).
  > • Daha önce aktardığınız evraklar tekrar indirilmez; yarıda kalan aktarım kaldığı yerden sürer.
  > • İsterseniz evrakları JurisAI yerine bilgisayarınıza, UYAP'taki klasör yapısıyla indirebilirsiniz.
  > • JurisAI web uygulamasındaki "UYAP Dosyalarım" bölümünden dosya listenizi görebilirsiniz.
  >
  > Gizlilik: UYAP/e-Devlet şifreniz, e-imzanız ve oturum çerezleriniz eklenti tarafından okunmaz ve saklanmaz. Hiçbir evrak kendiliğinden gönderilmez; yalnız onayladıklarınız aktarılır.
  > Eklenti yalnız UYAP ve JurisAI sayfalarında çalışır. Müvekkil verisi içerebileceğinden yalnız yetkili olduğunuz dosyalarda kullanın.
  >
  > Not: JurisAI hesabı ve bağlantı anahtarı gerekir. Eklenti UYAP'ın resmî bir ürünü değildir.

- **Görseller:** 128×128 simge (var: `images/icon-128.png`); en az 1, tercihen 3-5 ekran görüntüsü (1280×800): seçim penceresi, "UYAP Dosyalarım" listesi, aktarım özeti. **Ekran görüntülerinde gerçek müvekkil/taraf adı olmasın** (sahte dosya kullan).

## 4. Tek amaç beyanı

> Eklentinin tek amacı, kullanıcının UYAP'ta yetkili olduğu dosyalardan seçtiği evrakları kendi JurisAI hesabına (ya da isterse bilgisayarına) aktarmaktır.

## 5. İzin gerekçeleri (formda tek tek istenir)

| İzin | Gerekçe |
| --- | --- |
| `host: *.uyap.gov.tr`, `*.adalet.gov.tr` | Evrak ağacını okumak, evrak belgesini kullanıcının oturumuyla indirmek. Başka site yok. |
| `host: <API adresi>` | Seçilen evrakları kullanıcının JurisAI hesabına yüklemek. |
| `storage` | JurisAI bağlantı anahtarı ve ayarlar (hız, otomatik aktarım açık/kapalı) saklanır. |
| `webRequest` | UYAP'ın evrak önizlemesi için yaptığı belge isteğinin adresini (salt gözlem, engelleme/değiştirme yok) yakalamak; belge bu adresten indirilir. |
| `scripting` | Eklenti güncellendikten sonra açık UYAP/JurisAI sekmelerine yeni betiği yerleştirmek (sekmeyi yenileme gereği kalmaz). |
| `downloads` | Kullanıcı "bilgisayarıma indir"i seçince evrakları klasör yapısıyla İndirilenler'e kaydetmek; tanı raporu. |
| `activeTab` | Eklenti simgesine basılınca o sekmeye komut göndermek. |
| `content_scripts: bridge.js` (JurisAI sayfası) | JurisAI sayfasının "UYAP Dosyalarım" bölümünün eklentiyle konuşması; yalnız beyaz listedeki 3 komut (`PING`, `LIST_DOSYALAR`, `OPEN_DOSYA`). |

## 6. Veri kullanımı beyanları (Gizlilik uygulamaları sekmesi)

- **Toplanan veri türleri:** "Web sitesi içeriği" (UYAP evrakları, kullanıcının seçtikleri) ve "Kişisel olarak tanımlanabilir bilgi" (evrakların içeriği) ile "Kimlik doğrulama bilgisi" (JurisAI bağlantı anahtarı: yalnız kendi JurisAI'sına kimlik olarak gider). "Web geçmişi", "konum", "finansal", "sağlık", "kullanıcı etkinliği (tıklama kaydı)" **işaretlenmez**: eklenti bunları toplamaz.
- Üç taahhüt kutusunun üçü de işaretlenir: verileri onaylı kullanım dışında satmıyoruz/aktarmıyoruz; temel işlev dışı amaçla kullanmıyoruz; kredi/borç verme amacıyla kullanmıyoruz.
- **Uzaktan kod:** Yok. Tüm kod pakette; dışarıdan betik yüklenmez, `eval` kullanılmaz.
- **Gizlilik politikası URL'si:** bölüm 1'deki sayfa.

## 7. İnceleme notları (inceleme ekibine)

İnceleme ekibinin UYAP hesabı olmadığı için eklentinin çekirdek akışını canlı deneyemez; reddi önlemek için "Test talimatları" alanına şunlar yazılır:

> Eklenti UYAP'ta (vatandas.uyap.gov.tr / avukat.uyap.gov.tr) kullanıcının kendi e-Devlet/e-imza girişinden sonra çalışır; test için UYAP hesabı gerekir ve bu hesap paylaşılamaz (kişisel veri/e-Devlet). Akışı gösteren ekran kaydı: <bağlantı>. Eklenti şifre/çerez okumaz; yalnız kullanıcının seçtiği evrakların adresini yakalar ve belgeyi aynı oturumla indirip kullanıcının JurisAI hesabına yükler.

Ekran kaydı (2-3 dk, sahte/anonim dosyayla): giriş → dosya açma → evrak seçimi → aktarım özeti → JurisAI'da belgenin görünmesi.

## 8. Riskler ve açık işler

- **Mağaza reddi riski:** UYAP'tan veri okuyan eklentiler (LexPanel, Apilex vb.) mağazada yayında; yine de reddedilirse gerekçeye göre izin açıklamaları düzeltilir ve yeniden gönderilir.
- **Hukuki:** UYAP kullanım koşulları ve KVKK (müvekkil verisi, veri işleyen/sorumlu ayrımı) için avukat görüşü gerekir; gizlilik politikasındaki sorumluluk ayrımı bir taslaktır.
- **Gerçek UYAP doğrulaması:** Vatandaş Portalı ile denendi; **Avukat Portalı ile denenmedi** (test edecek avukat hesabı yok). Mağazaya çıkmadan önce bir avukatla Avukat Portalı üzerinde uçtan uca denenmeli.
- **Canlı alan adı** belli olunca: `--web-origin`/`--api-url` ile paket üretilir; JurisAI sayfasındaki köprü yalnız o kaynakta çalışır.
