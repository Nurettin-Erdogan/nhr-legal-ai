# JurisAI ↔ Apilex karşılaştırması (2026-10-04)

**Hedef:** önce Apilex'in sunduğu çekirdek iş akışlarına yetişmek, sonra doğrulanabilir kaynak ve KVKK alanında onlardan iyi olmak.
Apilex bir referanstır, birebir kopyalanmaz ([AGENTS.md](../AGENTS.md)).

## Sınırlar (önce bunları bil)

- Apilex'i **elle denemedim**: hesabım yok. Aşağıdaki Apilex bilgileri yalnızca kamuya açık sayfalardan, mağaza listelerinden ve üçüncü taraf bir
  karşılaştırma yazısından alındı; hepsi pazarlama iddiası sayılmalı. Hız, doğruluk ve arayüz kalitesi ölçülmedi.
- Bizim durumumuz **koddan ve bu oturumdaki canlı ölçümlerden** çıkarıldı. Bir avukatın gerçek kullanımıyla doğrulanmadı (test edecek avukat hesabı yok).
- "Yerel model" farkının kalite etkisini (aşağıda en büyük risk) ölçmedim.

## Apilex ne sunuyor (kamuya açık kaynaklara göre)

| Alan | İddia |
| --- | --- |
| Asistan | Araştırma + belge üretimi tek ekranda; yanıtlar mevzuat/karar atıflı, "%100 kaynaklı" |
| Karar arama | Semantik ("olayı anlat, anahtar kelime gerekmez"), "12 milyondan fazla güncel karar"; üst/ilk derece, kurul, AİHM |
| Projeler | Dava dosyası başına çalışma alanı, klasörleme, toplu analiz ("binlerce sayfa"), otomatik özet ve karşılaştırma tablosu, projeye özel asistan |
| Agent | Derin hukuki araştırma ve daha ayrıntılı belge üretimi |
| Belge | İki belgeyi kıyasla (fark + hukuki anlam), sözleşme risk analizi, dilekçe/sözleşme/ihtarname/görüş yazısı; PDF, DOC ve UYAP biçimleri; dilekçe ~1 dk |
| Entegrasyon | UYAP (Chrome eklentisi), Word, Google Drive, e-Tebligat |
| Mobil | iOS uygulaması (4,7/5, 271 değerlendirme) |
| Güvenlik | KVKK, ISO 27001/42001, GDPR, EU AI Act; SAML SSO, denetim günlüğü; kullanıcı verisiyle model eğitilmez; çok/tek kiracılı ve şirket içi kurulum seçenekleri |
| Pazar | TR, FR, DE aktif; İtalya, İspanya, Brezilya yolda |
| Fiyat | iOS'ta 1 ay ₺24.999,99, 6 ay ₺39.999,99; baro anlaşmalarıyla %25 indirim; soru sınırı yok |
| Güçlü/zayıf (üçüncü taraf) | Daha tutarlı, uzun belgelerde iyi, uygulama içi düzenleme, ayrı destek ekibi · zayıf: paket esnekliği |

Kaynaklar: [apilex.ai](https://www.apilex.ai/), [platform](https://www.apilex.ai/platform), [asistan](https://www.apilex.ai/tr/asistan),
[projeler](https://www.apilex.ai/tr/akilli-belge-yazim-platformu), [blog](https://www.apilex.ai/blog/turkiye-hukuk-sistemine-uygun-yapay-zeka),
[App Store](https://apps.apple.com/tr/app/apilex-hukuk-asistan%C4%B1/id6752776204?l=tr),
[Chrome eklentisi](https://chromewebstore.google.com/detail/apilex-ai-for-legal/eifhpjccnfcdaaeomidagonmkllcoogk),
[karşılaştırma yazısı](https://www.hukukiyapayzeka.com/2026/01/06/apilex-de-jure-karsilastirma/).

## Bizde bugün durum

✓ çalışıyor · ◐ kısmen · ✗ yok

| Özellik | Apilex | JurisAI | Not |
| --- | :-: | :-: | --- |
| Kaynaklı hukuk asistanı | ✓ | ✓ | Atıf **kodda doğrulanıyor**, doğrulanmamış kaynak ayrı işaretli, kaynak yoksa söylüyor. Yanıt 14-40 sn (yerel model). |
| Karar arama (anlamsal) | ✓ | ◐ | **Karar listesi arayüzü eklendi** (İçtihat Araştırması ve Semantik İçtihat sayfaları, commit'siz): kart başına mahkeme/daire, esas-karar no, tarih, eşleşen pasaj (vurgulu), doğrulama rozeti, tam metin, atıf kopyala; mercii/yıl/tür süzgeci, sıralama, "yalnız resmî doğrulanmış". İki mod: **anahtar kelime** (`/api/legal/search`) ve **olayı anlat** (`/api/legal/semantic`, sohbet hattının hibrit getirmesi, en iyi ~60 kaynak). Sınırlar: olay anlatımında konu dışı sonuç karışabiliyor (örn. işçilik anlatımında Sayıştay ilamları; ölçüldü, arayüzde "deneysel" ve uyarılı), soğuk ilk arama 10-40 sn, anlamsal arama yalnız resmî doğrulanmış kısımda (embedding). AI cevabı değil, kaynakların kendisi. |
| Mevzuat | ✓ | ✓ | Resmî Gazete + MBS çift doğrulamalı ~31,6 bin kayıt. Arayüzü sohbet kutusu. |
| Dava dosyası belgeleriyle soru-cevap | ✓ | ✓ | `case_id` kapsamlı RAG, OCR, UDF/ODT, çöp kutusu. |
| Projeler / klasörleme | ✓ | ◐ | Proje + belge yükleme var. Toplu özet/karşılaştırma **yapıştırma ile**; proje belgelerinden çalışmıyor. |
| Belge kıyaslama | ✓ | ◐ | **Dava sayfasına "Belge Kıyasla" sekmesi eklendi** (commit'siz): davaya bağlı iki belgenin cümle ve sözcük düzeyinde farkı (silinen/eklenen/değişen, üstü çizili/vurgulu rakam), belirleyici ve yapay zekâsız; rakam ve noktalama farkı her zaman görünür, OCR'lı belgede uyarı, uç nokta RLS'li ve denetim kaydı yalnız kimlik yazar. **Yok:** farkın hukuki anlamını açıklama (Apilex'in "fark + hukuki anlam" iddiası) — yerel model ve kaynak kuralı nedeniyle bilinçli olarak eklenmedi. Sınır: belge başına 400 bin karakter / 6 bin cümle. |
| Agent (derin araştırma) | ✓ | ◐ | **Gerçek çok adımlı hale getirildi** (commit'siz): soru üç sabit eksene (mevzuat, yargı kararları, süre/ispat/usul) bölünür, her eksen kaynaklı cevap hattından geçer (atıf kodda doğrulanır), rapor birleştirilir, kaynağı olmayan eksen açıkça yazılır, aynı cevap tekrarlanmaz. Eski sayfa korpusta olmayan "doktrin ve karşılaştırmalı hukuk" vaat ediyordu, kaldırıldı. Sınırlar: plan modelsiz sabit şablon (soruya göre uyarlanmaz), bölümler arası sentez yok (model metni doğrulanamayacağı için bilinçli), kalite getirme hattınınki; ölçülen süre ~40-50 sn. |
| Dilekçe/sözleşme üretimi | ✓ | ◐ | Üretim var, kaynak kuralı kodda; çıktı ≤ ~300 kelime (yerel model sınırı). Dışa aktarma: PDF, DOCX, TXT. **UDF/UYAP biçimi yok.** |
| Risk analizi | ✓ | ◐ | Modül var, gerekçeli değerlendirme (kesin tahmin vermiyor, bilinçli). |
| UYAP | ✓ | ◐ | Kendi Chrome eklentimiz: dosya listesi, evrak ağacı (kalıcı kimlik), seçerek aktarım, klasör yolu. Gerçek aktarım ve avukat portalı doğrulanmadı; mağazada değil. |
| e-Tebligat | ✓ | ✗ | |
| Word / Google Drive | ✓ | ✗ | Google yalnızca giriş için. |
| Müvekkil, dava, takvim, görev, hatırlatma | ◐ | ✓ | Çalışıyor (genel CRUD); derinliği Apilex'inkiyle karşılaştırılamadı. |
| İcra takibi, aday takibi, raporlar, personel, tahsilat | ? | ✗ | Sayfalar dürüstçe "henüz bağlı değil" diyor. |
| Abonelik / ödeme | ✓ | ✗ | Herkes ücretsiz; ödeme akışı yok. |
| Mobil uygulama | ✓ | ✗ | Yalnız web. |
| Güvenlik | ✓ | ◐ | RLS, denetim kaydı, oturum iptali, giriş kısıtı, yerel model (veri buluta gitmiyor). Sertifika, SAML SSO, kurumsal gizlilik merkezi yok. |
| Çok dilli/ülkeli | ✓ | ✗ | Yalnız Türkçe/TR. |

**Korpus (karar sayısı karşılaştırması adil değil):** ~11,3 M kayıt, ama ~10,9 M'u üçüncü taraf toplu veri
(`bulk_seed`, doğrulanmadı); bunlar aranır ama "resmî" diye sunulmaz. **Resmî doğrulanmış (`ready`) kayıt: 385.297** (235.568 karar, 56.402 mevzuat,
93.327 diğer). Embedding ve dolayısıyla anlamsal arama yalnız bu resmî kısımda var. "12 milyon karar" iddiasına sayı olarak yetişmek hedef değil: bizim
satış noktamız doğrulanmış kısmı ayrı göstermek ve büyütmek.

## Bu oturumda ölçülen sağlık durumu (karşılaştırmayı etkiler)

- `/api/legal/stats` **düzeltildi** (commit'siz): `count(*)` 35 sn sürdüğünden uç 503 veriyordu. İstatistik artık diske yazılıyor, API yeniden başlayınca
  oradan okunuyor, ağır sayım arka planda yenileniyor (uç ms'de 200). Korpus paneli ve "Karar Hukuku" paneli yeniden veri gösteriyor.
- Araştırma sayfası (`/api/ai/sources`) yaygın konularda 90 sn'yi aşıp 504 veriyordu; sınırlı arama ile 6-18 sn'ye indi (commit'siz). Arama sonuçlarına
  `verification` alanı eklendi (resmî / üçüncü taraf / bilinmiyor).
- Soğuk hukuk araması ~16 sn (DB embedding yazımlarıyla meşgul); olay anlatımında ilk arama 10-40 sn, sonrası önbellekten ms.

## Önerilen yol

**Aşama 1: Apilex'e yetişme** (etki/emek sırasıyla)
1. ~~**Karar arama sonuç ekranı**~~ **yapıldı** (commit'siz): kart listesi, süzgeçler, tam metin, iki mod. Açık: olay anlatımında alaka kalitesi (paylaşılan getirme hattı; Sayıştay/KDK gürültüsü), hız.
2. ~~**`/api/legal/stats`'ı düzelt**~~ **yapıldı** (commit'siz).
3. **Projelerde toplu özet ve belge kıyaslama:** ~~iki belgenin fark görünümü~~ **yapıldı** (commit'siz). **Toplu özet de yapıldı:** dava sayfasında "Dosya Özeti" sekmesi: (1) olgu tablosu (tarih, tutar, esas/karar, kanun no; regex, yapay zekâsız; kimlik numaraları çıkarılmaz), (2) belge belge yapay zekâ özeti (arka plan işi, pencere pencere + birleştirme; sunucuda belgeyle doğrulama: belgede olmayan rakam/numara ve zayıf dayanaklı madde elenir, elenen sayı ve kapsam oranı gösterilir, sonuç kaydedilir). Sınır: belge başına en çok 6 pencere (~17 bin karakter), işte en çok 10 belge; doğrulama mantıksal hatayı yakalamaz (örn. uydurma başlık), arayüz "belgeyle karşılaştırın" der.
4. **Belge çıktısı:** UDF/UYAP biçimi, uzun belge (yerel model çıktı sınırı), uygulama içi düzenleme. **UDF yazımı bilerek yapılmadı:** gerçek UYAP editöründe açılıp açılmadığını doğrulayamıyoruz (avukat hesabı yok); açılmayan bir UDF avukata zarar verir. UDF *okuma* var.
5. **UYAP eklentisi:** gerçek aktarım testi, JurisAI içinde evrak seçimi, Chrome Web Mağazası (güncelleme + güven).
6. **Ödeme/abonelik** altyapısı (ticari ürün için şart) ve fiyat konumu: Apilex ₺25-40 bin aralığında, sınırsız soru.
7. Hız: model/ısınma; yanıt süresi 14-40 sn Apilex'in "dilekçe ~1 dk" iddiasıyla aynı sınıfta ama yavaş.

**Aşama 2: onlardan iyi olma** (bizim güçlü yanımız)
- **Kanıtlanabilir doğruluk:** Apilex "%100 kaynaklı" diyor; biz her cümlenin hangi kaynağa dayandığını göstererek ve desteği kodda doğrulayarak **kanıtla**. Cümle bazlı atıf, "kaynak metni göster", yeşil/sarı doğrulama durumu.
- **Resmî/doğrulanmamış ayrımı** her ekranda ve resmî doğrulama oranı görünür bir güven göstergesi.
- **KVKK:** yerel model varsayılan (müvekkil verisi buluta gitmez). Apilex şirket içi kurulumu kurumsal seçenek olarak sunuyor; bizim varsayılanımız.
- **UYAP:** seçerek aktarım, klasör yapısı, yinelenen önleme, yarıda kalanı sürdürme.
- Kaynak yetersizse bunu açıkça söyleme (uydurmama) bir satış noktası.

## Riskler

- **Model kalitesi** en büyük açık olabilir: yerel 4B model (qwen3.5:4b) ile bulut modellerin farkı. Ölçmeden iddia etmiyorum; avukatlarla aynı sorular üzerinde yan yana test gerekir.
- Apilex iddiaları doğrulanamaz (12 M karar, "%100 kaynaklı"); eşitlik hedefini onların gerçek davranışını görmeden koymayın. Bir demo hesabı (baro demosu: apilex.ai/istanbulbarosudemo) açılabilir.
- Sertifika (ISO/KVKK) ve SAML SSO kurumsal satışta fark yaratır; maliyetli, ilk aşama dışında.

## Ölçülen cevap kalitesi (2026-10-04, `scripts/eval_live_answers.py`, canlı API, 20 sabit soru)

Kod kontrolleri (hukuki doğruluğu ÖLÇMEZ, avukat değerlendirmesi gerekir): kaynağa dayalı 19/20, atıflı 19/20, beklenen kaynak türü 18/20, soru terimleri cevapta 17/20,
doğrulanmamış (üçüncü taraf) atıf oranı 0, süre medyan 22,7 sn (en çok 37 sn). "Beklenen kanun atıflarda" 8/20 ve "beklenen madde" 14/20: ölçüt kaba (karar atıflarında kanun alanı
boş olabiliyor; "kıdem" sorusunun beklentisi 4857 ama kıdem tazminatı 1475 m. 14'te), gerçek hata oranı olarak okunmamalı. Ölçümün yakaladığı gerçek hata: "4857 sayılı İş Kanunu
madde 18 neyi düzenler?" doğru maddeyi bulduğu hâlde "yeterli kaynak yok" diyordu (soru kalıbı sözcükleri "neyi/düzenler" pasajda geçmediği için alakasız sayılıyordu); düzeltildi
(`api/ai/relevance.py`, test eklendi). Bu, bulut modellerle karşılaştırma DEĞİLDİR.

## Kullanılabilirlik turu (2026-10-05, commit'siz)

- **Mevzuat sayfası gerçek mevzuata bağlandı.** Eskiden menüdeki "Mevzuat" genel bir sohbet kutusuydu (mevzuat verisini kullanmıyordu). Şimdi: ~4.000 resmî doğrulanmış güncel mevzuat (kanun, KHK, yönetmelik, tebliğ, Anayasa) ad/numara/"4857 m. 18" ile aranır (Türkçe karakter katlamalı), madde dizini madde numarası sırasıyla gezilir, madde okunur, önceki/sonraki madde, atıf kopyala, resmî kaynak bağlantısı. Doğrulanmamış mevzuat listelenmez.
- **Ana sayfa gerçek bir panel oldu:** yaklaşan duruşmalar, açık görevler (gecikmiş sayısı), son davalar, boş hesapta yönlendirme; hızlı erişimde Derin Araştırma ve Mevzuat.
- **Menü:** "Hukuki Araştırma" (asistanın kopyası) yerine "Derin Araştırma".
- Hâlâ "henüz bağlı değil" (menüde yok): İcra Takibi, Müvekkil Adayları, Raporlar, Personel.

## Kullanıcı gözüyle test (2026-10-05, commit'siz)

Yeni hesapla gerçek akış denendi. **Bulunan en büyük hata:** Dilekçe/Sözleşme üretimi, Belge Analizi, Risk Analizi ve Toplu Özet'in altısı da hata veriyordu (502 "token sınırında kesildi" ya da 422 "kaynaklarla desteklenemedi"): serbest biçimli taslak `[K1]` atıf denetiminden geçemiyordu. Yeniden tasarlandı (`api/draft_documents.py`, `api/office_analysis.py`):

- **Taslak:** iskelet kodla kurulur (başlıklar, taraflar, SONUÇ VE İSTEM, boşluklar `[…]`); model yalnız olay anlatımını yazar ve her paragraf kodda verilen bilgiyle doğrulanır (uydurma tutar/tarih/numara/kanun ve zayıf dayanaklı paragraf elenir; hiçbiri kalmazsa kullanıcının kendi olguları aynen kullanılır); **hukuki nedenler modele yazdırılmaz**, korpustan gelen resmî doğrulanmış mevzuat ve kararlar kodla listelenir, kaynak yoksa bu söylenir.
- **Belge analizi / toplu özet:** doğrulanmış özet + belgede geçen olgular + otomatik bulunan resmî kaynak listesi; hukuki değerlendirme yok.
- **Risk analizi:** dava sonucu tahmini yok; olay mevzuat / yargı kararları / süre-ispat başlıklarında kaynaklı incelenir.
- **PDF dışa aktarma:** jsPDF yerleşik yazı tipi ş ğ ı İ harflerini bozuyordu; Liberation Sans gömüldü, Türkçe PDF doğrulandı.
- Sınır: 4B model olgu paragraflarını sık süsler; kod bunları eler, taslak çoğu zaman kullanıcının kendi olgu cümleleriyle kurulur (üslup düzeltmesi avukata kalır).

Çalışan akışlar (denendi): kayıt/giriş, müvekkil, dava, görev, takvim, belge yükleme, OCR (taranmış dilekçe 538 karakter), asistan, mevzuat, içtihat, Dosya Özeti, Belge Kıyasla, Derin Araştırma.

### Yerel model kıyası (2026-10-05, aynı 20 soru, `scripts/eval_live_answers.py`)

| | qwen3.5:4b (varsayılan) | deepseek-r1:8b |
| --- | --- | --- |
| Kaynağa dayalı | 19/20 (düzeltmeden önce; "madde 18" hatası giderildi, 20/20 beklenir) | 14/20 |
| Atıflı cevap | 19/20 | 14/20 |
| Soru terimleri cevapta | 17/20 | 12/20 |
| Süre medyan / en çok | 22,7 / 37 sn | 23,5 / 61 sn |

Sonuç: daha büyük yerel model bu hat ve istemlerle **daha kötü** (kaynaklı cevap veremediği soru sayısı arttı, aynı hız); varsayılan model değiştirilmedi. Bu bulut modellerle kıyas DEĞİLDİR (anahtar yok) ve hukuki doğruluğu ölçmez.

### Telefon ve KVKK (2026-10-05)
- 16 sayfa telefon genişliğinde (390 px) yatay taşmasız; uygulama yüklenebilir (PWA: manifest, simge, yalnız çevrimdışı sayfa önbelleğe alan servis çalışanı; API/belge/sohbet önbelleğe alınmaz).
- Ayarlar > "Verilerimi indir (JSON)": kullanıcının kendi verileri (parola, anahtar, iç yol hariç).

### Menü düzeni (2026-10-05)
Kenar çubuğu 5 gruba ayrıldı (Büro, Hukuki araştırma, Belge üretimi ve analiz, Dosyalar ve UYAP, Hesap; 22 bağlantı). Daha önce yalnızca adresle ulaşılabilen **Müvekkiller, Görevler, Takvim, Hatırlatmalar, Belge Analizi, Toplu Özet, Risk Analizi ve Semantik İçtihat** menüye bağlandı. "Henüz bağlı değil" diyen sayfalar (İcra, Müvekkil Adayları, Raporlar, Personel, Tahsilat, Aramalar) bilerek menüde yok. Risk/Belge Analizi/Toplu Özet sayfalarındaki vaatler gerçek davranışa uyduruldu ("dava sonucu tahmini", "tavsiye" ifadeleri kaldırıldı). Menü bir testle korunur (`web/tests/nav.test.mjs`): her girdi gerçek bir sayfaya gider, çalışan her sayfa menüde olmalıdır.

## Apilex taraması (2026-10-05, kamuya açık kaynaklar; elle denenmedi)

**Kaynak güvenilirliği:** hepsi pazarlama, haber bülteni ya da üçüncü taraf yazıdır. **YouTube videolarının içeriğine erişilemedi** (yalnız başlık ve kanal): "APİLEX - HUKUK YAPAY ZEKA ASİSTANI | Kullanıcı Deneyimi ve İnceleme" (Bayram Oğuz Güngör), "Apilex AI İncelemesi" (M. Ufuk Tekin; dilekçe modülü), "Apilex Kullanan vs Kullanmayan Avukat". Videolarda ne gösterildiği bilinmiyor; transkript ya da ekran notları verilirse analiz edilir.

**Şirket:** APILEX TEKNOLOJİ A.Ş. (İstanbul; bazı kaynaklarda "Apilex Fitty Tek. A.Ş."). Kurucular: Av. Cebrail Ergül, Kemal Tamer, Batuhan İpek. 2026'da Almanya, Fransa, İspanya, İtalya'ya açılma hedefi. Kütahya Barosu ile üyelere %25 indirim protokolü.

**Ürün (resmî sayfalar):** Asistan (araştırma + belge üretimi tek ekranda); semantik karar arama ("olayı anlat"); Projeler (dosya başına çalışma alanı, **toplu analiz**, otomatik özet, **"kritik farklar ve ortak noktalar" tablosu**, projeye özel asistan, geçmiş çalışmaları bilgi kaynağı yapma); Agent (derin araştırma); belge kıyaslama; risk analizi; sözleşme/dilekçe analizi; Word, Google Drive, UYAP (Chrome eklentisi, tek tıkla dosya indirme) ve e-Tebligat entegrasyonu; **UDF indirme**; iOS ve Android uygulaması (takvim, dava yönetimi, Resmî Gazete özetleri); "yazım üslubuna uyarlama" iddiası.

**Güvenlik/uyum iddiaları:** KVKK, GDPR, EU AI Act, ISO 27001 (2022) ve ISO 42001 listeleniyor; SAML SSO, denetim günlüğü, veri yaşam döngüsü; çok kiracılı / tek kiracılı / **şirket içi (on-premise)** seçenek; girdi-çıktı model eğitiminde kullanılmaz; uçtan uca şifreleme; "Legal Engineer" ekipleri veri doğruluyor. Doğruluk iddiası: "her yanıt karar numarası ve mevzuat referansıyla" ve çok katmanlı halüsinasyon kontrolü; **kodla doğrulama ayrıntısı yayımlanmamış.**

**Rakamlar (tutarsız):** karar sayısı bir yerde 12 milyon, bir yerde 11 milyon; doktrin de dahil denir. iOS fiyatı: 1 ay ₺24.999,99, 6 ay ₺39.999,99; üçüncü taraf yazılarda 6 ay ₺25.000 / yıllık ₺40.000 (kaynaklar uyuşmuyor). Soru sınırı yok iddiası. Chrome eklentisi v1.0.25, ~8.000 kurulum, 5,0 (8 oy). App Store 4,7 (271 değerlendirme).

**Kullanıcı sinyalleri:** App Store'da övgü (rakiplerden iyi, hızlı destek) ve beklenmedik ücret şikâyeti. **Şikâyetvar'da 4 şikâyet:** arama hatalarının çoğunda sistem hatası, yavaşlık, yetersiz destek ("çalışmalar sürüyor" cevabı), **Nisan'da vaat edilen UYAP/e-Tebligat entegrasyonunun gecikmesi**, izinsiz tanıtım araması. Tek karşılaştırma yazısı (De Jure ile) Apilex'i üstün buluyor ama kendisi "laboratuvar testi değil" ve bizzat test kanıtı yok.

### Bizde hâlâ olmayan (Apilex'te iddia edilen)
1. **Çok belgeli karşılaştırma tablosu** ("farklar ve ortak noktalar"): bizde yalnız iki belgenin metin farkı var.
2. **Karar karşılaştırması** (benzer kararları yan yana): yok.
3. **Word eklentisi, Google Drive, e-Tebligat** (UYAP'ın yanında); **native iOS/Android** (bizde PWA).
4. **UDF çıktısı** (bkz. doğrulama sorunu).
5. **Yazım üslubuna uyarlama**, **Resmî Gazete özeti**, **doktrin** kaynakları.
6. SSO, sertifikalar, kurumsal yönetim; ödeme.

### Apilex'in zayıf göründüğü yerler (bizim fırsatımız; yalnızca kullanıcı şikâyetlerine dayanır)
- **Güvenilirlik ve hız** (sık hata, yavaşlık), **destek** ve **tutulmayan entegrasyon vaatleri**.
- **Kanıtlanabilirlik:** doğruluk "iddia"; biz atıfı ve desteği kodda doğruluyor, resmî/doğrulanmamış ayrımını her ekranda gösteriyoruz. **Veri yeri:** bizde varsayılan yerel (müvekkil verisi dışarı çıkmaz); onlar için bu "on-premise" ek seçenek.
- **Fiyat:** ₺25-40 bin; bizim fiyat kararımız yok.
