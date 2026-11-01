# Apilex referans analizi ve Faz 1 kapsamı

Tarih: 2026-09-21. Kaynak: Apilex'in **herkese açık** sayfaları, mağaza kayıtları, baro duyuruları ve
bağımsız yorumlar (sonda). Giriş gerektiren uygulamaya girilmedi, hesap açılmadı.

## Önce sınırlar

* **`AGENTS.md`:** "Apilex referanslardan biridir, birebir kopyalanmaz." Faz 1 hedefi *işlev eşdeğerliği*
  olarak okunmalıdır: aynı işleri yapan, kendi tasarımı, kendi metinleri ve kendi veriyle çalışan bir ürün.
  Arayüzün, marka dilinin, metinlerin ve görsellerin aynısı yapılmaz (marka/telif riski). Politika
  değişecekse `AGENTS.md` önce güncellenmelidir.
* **Apilex kullanım koşulları** (kullanıcılar için): rakip ürün geliştirme amacıyla kullanım, ters
  mühendislik, veri kazıma ve model taklidi yasak. Bu yüzden Apilex'e deneme hesabıyla girip ekran ekran
  çıkarma **yapılmamalı**; bu analiz yalnız herkese açık bilgiye dayanıyor.
* **Doğrulama düzeyi:** Aşağıdaki her madde "sayfada yazıyor" (Ⓟ), "üçüncü taraf kaynak" (Ⓣ) ya da
  "doğrulanamadı" (Ⓧ) olarak işaretlidir. Pazarlama iddiaları ölçülmüş performans değildir.

## 1. Apilex ne sunuyor

### Ürün modülleri

| Modül | Ne yaptığı (kaynağın anlatımı) | Düzey |
| --- | --- | --- |
| **Asistan** | Hukuki soru-cevap, mevzuat ve içtihat atıflı cevap, belge üretimi, dosyalar hakkında soru | Ⓟ |
| **Agent** | "Daha derin araştırma ve detaylı belge üretimi" (ayrıntı verilmiyor) | Ⓟ, ayrıntı Ⓧ |
| **Semantik karar arama** | Somut olayı anlatarak karar bulma; mahkeme/daire/konu/tarih filtreleri; sonuç puanlama/sıralama | Ⓟ (filtre ayrıntısı bir sayfada yok) |
| **Projeler** | Dava dosyalarını tek alanda toplama, proje özelinde analiz, dosya senkronizasyonu; dosyadan taraf ve dava konusunu otomatik çıkarma, dosya özeti | Ⓟ |
| **Hukuki analiz** | Olgu/konu/argüman çıkarma, risk analizi (davanın güçlü/zayıf yönü), mevzuat takibi, kaynak önerisi, rapor | Ⓟ |
| **Belge yazımı** | Dilekçe, sözleşme, ihtarname, görüş yazısı; özel şablon; "her zaman kaynaklı"; Word'e aktarım | Ⓟ |
| **Belge analizi** | Sözleşmede riskli/eksik/çelişkili hüküm işaretleme, redaksiyon önerisi, toplu sözleşme yönetimi | Ⓟ |
| **Toplu özet ve karşılaştırma tablosu** | Birden çok karar/belge için özet ve yan yana tablo ("Auto Summary") | Ⓟ (EN sayfa) |
| **Hukuki tahmin** | Adı geçiyor, nasıl çalıştığı yok | Ⓟ, ayrıntı Ⓧ |
| **Otomatik iş akışları** | Dava takip (duruşma hatırlatma, vade, süre kontrolü), sözleşme yenileme, müvekkil bildirimleri; e-imza, UYAP, takvim, e-posta | Ⓟ. Sayfada "%75 ilerleme" gibi arayüz maketi var; canlı özellik olmayabilir Ⓧ |
| **UDF dönüştürücü** | UDF → PDF/DOCX/Markdown, sürükle-bırak, ücretsiz araç görünümünde | Ⓟ |

### Yüzeyler (nerede çalışıyor)

| Yüzey | Ayrıntı | Düzey |
| --- | --- | --- |
| Web uygulaması | `app.apilex.ai`, giriş/kayıt | Ⓟ |
| **UYAP Chrome eklentisi** | "UYAP dosyalarınızı otomatik senkronize edin"; v1.0.22, 16 Eyl 2026 güncel, 7.000+ kullanıcı; işlediği veri: kişisel tanımlayıcılar, web geçmişi, site içeriği | Ⓟ (mağaza) |
| **Word eklentisi** | Microsoft Marketplace; belgeyi Word'den analiz et/oluştur, çıktıyı doğrudan Word'e aktar; **bireysel self-servis kayıt yok**, kurum yöneticisi ya da demo yoluyla | Ⓟ (mağaza) |
| iOS/macOS uygulaması | 4.7★ (258 değerlendirme); kaynaklı soru-cevap, içtihat ve mevzuat arama, dilekçe editörü (otomatik doldurma), takvim entegrasyonu, dosya yükleme, PDF ve **UDF dışa aktarma**; uygulama içi satın alma | Ⓟ |
| Android | Google Play `ai.apilex.app` | Ⓟ |
| Google Drive | Dosya erişimi | Ⓟ |
| Diller / ülkeler | TR/EN/FR/DE site; uygulama 7 dil; aktif: Türkiye, Fransa, Almanya; yakında: İtalya, İspanya, Brezilya | Ⓟ |

### Güven, güvenlik ve ticari model

* **Uyumluluk iddiaları:** KVKK, GDPR, ISO 27001, ISO 42001, EU AI Act. SSS ayrıca "SOC 2" diyor; iki sayfa
  tutarlı değil, sertifika kanıtı yok Ⓧ. SAML SSO, denetim günlüğü, "veri egemenliği", "modelde kullanıcı
  verisi eğitim için kullanılmaz" platform sayfasında yazıyor Ⓟ. Çok kiracı/tekil sunucu/on-premise
  seçenekleri bir blog yazısında geçiyor Ⓟ. DPA ve alt işleyici sayfaları var; alt işleyici listesi
  boş, hangi model/bulut sağlayıcısını kullandıkları **açıklanmıyor** Ⓧ.
* **Veri kaynağı iddiası:** "11 milyondan fazla içtihat" (başka sayfada 12 milyon, ayrıca "milyonlarca").
  Kapsam: Yargıtay, Danıştay, BAM, idare mahkemeleri, AYM, ilk derece, kurullar, AİHM. Sayı ve doğruluk
  bağımsız doğrulanmadı Ⓧ. "%100 kaynaklı", "%95 doğruluk", "10 kat hızlı", "%85 zaman tasarrufu" pazarlama
  ifadeleridir Ⓧ.
* **Fiyat:** Resmî sayfada yok, "Demo Talep Et". Kullanıcı yorumları ve bağımsız yazıya göre **6 ay 25.000 TL,
  yıllık 40.000 TL**, soru/özellik sınırı yok; iOS'ta uygulama içi ₺24.999,99–39.999,99 Ⓣ. Ödeme: PayTR,
  iyzico, Pay'nkolay Ⓟ.
* **Dağıtım (pazarlama):** Baro protokolleri (ör. Kütahya Barosu üyelerine %25 indirim; Trabzon, Şanlıurfa,
  Antalya duyuruları), baroya özel demo sayfaları (Ankara, Bingöl, Ordu, Trabzon), ücretsiz demo, 125+ SEO
  hukuk makalesi, ücretsiz UDF aracı ve UYAP eklentisi Ⓟ/Ⓣ.
* **Şirket:** Apilex Teknoloji A.Ş.; kurucu Av. Cebrail Ergül; başka ekip bilgisi yok Ⓟ.

### Kullanıcı ve bağımsız gözlemler (Ⓣ)

* **Övülen:** dilekçe/sözleşme üretimi (~1 dk), risk analizi, emsal gösterme, karmaşık dosyada tutarlılık,
  uygulama içi düzenleme (indirmeden), hukuki çerçeveyi sonuçtan önce sunma.
* **Eleştirilen:** fiyat, "uydurma karar" sorununun *büyük ölçüde ama tam değil* çözülmesi, verinin nereye
  gittiğinin belirsizliği. Bağımsız karşılaştırma (hukukiyapayzeka.com) yazarın bağımsızlığı doğrulanamadı.

### Bilinmeyenler

Arayüzün iç yapısı, kullanılan model/altyapı, gerçek arama kalitesi ve gecikme, Agent'ın gerçek yetenekleri,
iş akışlarının canlı olup olmadığı, SSO/SOC2 gerçekliği, gerçek veri kapsamı. Bunlar herkese açık kaynaklardan
çıkarılamaz; tahmin edilmemeli.

## 2. Bizde durum (kodda doğrulandı)

| Alan | Apilex | NHR Legal AI |
| --- | --- | --- |
| Kaynaklı soru-cevap | Var | **Var**, atıf işaretleri kodda doğrulanıyor; resmî/üçüncü taraf rozeti |
| Çok turlu sohbet, geçmiş | Var | **Var** (bu oturumda eklendi) |
| Semantik karar arama | Var | **Kısmi:** sözcüksel arama; embedding ~%6 hazır, sorgu embedding'i kapalı |
| Karar arama filtreleri | Var | **Yok** (arayüzde yok; API'de yalnız `as_of`) |
| Projeler, belge yükleme | Var | **Var** (PDF/DOCX/TXT; OCR yok; silme/görüntüleme yok) |
| Dosya otomatik analizi (taraf/konu/özet) | Var | **Yok** |
| Belge özeti, olgu/argüman çıkarma | Var | **Yok** |
| Sözleşme risk analizi | Var | **Yok** |
| Karar karşılaştırma, toplu özet tablosu | Var | **Yok** |
| Dilekçe/sözleşme üretimi, şablon, editör | Var | **Yok** |
| Dışa aktarma (Word/PDF/UDF) | Var | **Yok** |
| UYAP eklentisi | Var | **Yok** |
| Word eklentisi | Var | **Yok** |
| Takvim, süre/duruşma takibi, bildirim | Var (iş akışı) | **Yok** |
| Müvekkil yönetimi | Var (bildirim) | **Şemada var**, API/arayüz yok |
| Mobil | iOS/Android | **Yok** |
| Çok dil | 4–7 dil | **Yok** |
| SSO, denetim günlüğü | İddia | **Denetim günlüğü var**; SSO yok |
| Abonelik, ödeme, demo, baro protokolü | Var | **Yok** |
| Veri kapsamı | İddia: BAM, ilk derece, AİHM… | Yargıtay/Danıştay/AYM/KDK/mevzuat; çoğu doğrulanmamış (veri tarafı bu belgenin dışında) |

## 3. Faz 1 önerisi: işlev eşdeğerliği

Sıra, bağımlılıklara ve riske göre. Her başlık ayrı bir iş; hepsi Faz 1'de biter demek değil.

**A. Çekirdek (asistan kalitesi ve arama)**
1. Semantik/hibrit aramanın açılması (embedding tamamlanması + sorgu embedding'i + indeks kullanımı). *Veri tarafına bağlı.*
2. Karar arama arayüzünde filtreler (mahkeme, daire, tarih, tür) ve puanlı sıralama.
3. Model kalitesi: yerel 3B tavan; bulut sağlayıcı kararı bekliyor (KVKK), yerel modeller (gemma3:4b, qwen3:4b) alternatif.

**B. Belge işleri (Apilex'in en görünür değeri)**
4. Belge üretimi: dilekçe, sözleşme, ihtarname, görüş yazısı; şablon; kaynaklı üretim; uygulama içi editör.
5. Dışa aktarma: DOCX, PDF ve UDF. UDF biçimi ayrıca araştırılmalı (yayımlanmış bir şartname bulunamadı).
6. Belge analizi: özet, olgu/argüman çıkarma, sözleşme risk analizi, karşılaştırma tablosu.
7. Belge yönetimi tamamlanması: silme, tek belge görüntüleme, tekrar yükleme engeli, OCR.
8. Projede dosya özeti ve taraf/konu çıkarma.

**C. Entegrasyon ve iş akışı**
9. Word eklentisi (Office.js).
10. UYAP entegrasyonu (tarayıcı eklentisi). **Yüksek risk:** UYAP kimlik doğrulaması, kullanım koşulları ve KVKK etkisi hukuken incelenmeli; Apilex'in eklentisi "web geçmişi ve site içeriği" izni istiyor.
11. Dava takip: duruşma/süre hatırlatma, takvim, müvekkil kaydı ve bildirimleri.

**D. Ticari ve kurumsal**
12. Abonelik ve ödeme, demo talebi, baro protokolü kodları, KVKK/DPA/alt işleyici sayfaları, SSO.
13. Mobil (önce PWA), çok dil.

**Bizde korunacak farklar:** kaynak doğrulama durumunun şeffaf gösterimi, tarihe göre mevzuat sürümü,
kod tarafında atıf doğrulaması, isteğe bağlı yerel model. Apilex bunları sayfalarında anlatmıyor.

## 4. Açık kararlar (kullanıcıya ait)

1. "Aynı uygulama" = işlev eşdeğerliği mi, yoksa görsel/metin benzerliği de mi? (Öneri: yalnız işlev; `AGENTS.md` ve marka riski.)
2. Bulut model kullanımı ve buluta gidebilecek veri sınırı (KVKK).
3. UYAP entegrasyonunun kapsamı ve hukuki incelemesi.
4. Fiyat/ticari model ve baro kanalı.
5. Veri kapsamı (BAM, ilk derece, AİHM, kurullar) ayrı iş kolu; bu belgenin dışında.

## Kaynaklar

* [Apilex — Platform](https://www.apilex.ai/tr/platform), [Asistan](https://www.apilex.ai/tr/asistan), [İçtihat arama](https://apilex.ai/ictihat-arama-motoru), [Hukuki analiz](https://www.apilex.ai/tr/hukuki-analiz-ve-arastirma), [Belge yazımı](https://www.apilex.ai/tr/akilli-belge-yazim-platformu), [Otomatik iş akışları](https://www.apilex.ai/tr/otomatize-is-akislari), [UDF dönüştürücü](https://www.apilex.ai/tr/udf-donusum), [SSS](https://www.apilex.ai/tr/sss), [EN ana sayfa](https://www.apilex.ai/en), [Kurucudan mesaj](https://www.apilex.ai/tr/kurucudan-mesaj)
* [Kullanım koşulları](https://www.apilex.ai/kullanim-kosullari), [Gizlilik merkezi](https://www.apilex.ai/tr/gizlilik-merkezi), [Ankara Barosu demo sayfası](https://www.apilex.ai/tr/ankarabarosudemo), [Blog](https://www.apilex.ai/tr/blog)
* [Chrome Web Store — Apilex UYAP eklentisi](https://chromewebstore.google.com/detail/apilex-ai-for-legal/eifhpjccnfcdaaeomidagonmkllcoogk)
* [Microsoft Marketplace — Apilex Word eklentisi](https://marketplace.microsoft.com/en-us/product/web-apps/wa200010448?tab=overview)
* [App Store — Apilex: Hukuk Asistanı](https://apps.apple.com/tr/app/apilex-hukuk-asistan%C4%B1/id6752776204?l=tr), [Google Play](https://play.google.com/store/apps/details?id=ai.apilex.app&hl=en_US)
* [Kütahya Barosu protokolü](https://kutahyabarosu.org.tr/kurum/apilex-fitty-tek-a-s-yapay-zeka-hukuk-asistani/), [Trabzon Barosu](https://www.trabzonbarosu.org.tr/Detay/apilex-25-315720)
* [Bağımsız karşılaştırma: Apilex ve De Jure](https://www.hukukiyapayzeka.com/2026/01/06/apilex-de-jure-karsilastirma/)
