# UYAP denetimi — 8 Ekim 2026

## İlk denetimin sonucu ve kapsamı

**Canlı kabul tamamlanmadı; UYAP aktarımı için hatasız/yayına hazır sonucu verilemez.**
Bu denetimde mevcut hesabın kayıtları ve fiziksel belgeleri salt okunur incelendi.
Kullanıcı belgesi silinmedi, canlı aktarım veya yeniden indeksleme başlatılmadı.
Uygulama kodu değiştirilmedi. Kontroller `feature/legal-ai` dalındaki mevcut,
başka geliştirmeler de içeren çalışma ağacında yapıldı.

Windows tarayıcı kontrol yardımcısı `helper_unknown_error: setup refresh had errors`
ile başlatılamadı. Bu nedenle açık Chrome/UYAP oturumuyla yeni bir karşılaştırma
yapılamadı. Aşağıdaki kayıtlı aktarım sonuçları yeni canlı test sonucu değildir.

## Kayıtlı belgelerin bütünlüğü

- 1.398 aktif UYAP belgesinin fiziksel dosyası bulundu.
- Dosya boyutu ve SHA-256 özeti kayıtlarla eşleşti: 0 hata.
- Eksik dosya/birim/evrak kimliği veya dava bağlantısı: 0.
- Aynı dosya, birim ve evrak kimliğiyle mükerrer kayıt grubu: 0.

Bu kontroller kaydedilmiş dosyaların sağlamlığını gösterir; UYAP'taki tüm
belgelerin alındığını veya içeriğin doğru evrak olduğunu tek başına kanıtlamaz.
Son rapordaki 1.380 kayıt ile mevcut 1.398 aktif kayıt aynı ölçüm değildir.
Fazladan görünen 18 kayıt farklı evrak kimlikleri taşır; bu denetimde bunların
mükerrer/yanlış olduğuna karar verilmedi ve kayıtlar silinmedi.

## Son saklanan UYAP karşılaştırması

Son kayıt zamanı: **7 Ekim 2026 20:46:53 Türkiye saati**.
Veritabanında evrak bulunan 19 davanın doğrulama kaydı mevcut.
Kullanıcının 21 dosyalık raporundaki iki evraksız dosya ayrı değerlendirilmelidir;
19 veritabanı satırı üzerinden 21 dosyanın bugün doğrulandığı söylenemez.

| Dosya | Kayıtlı sonuç | Açık sorun |
| --- | --- | --- |
| 2024/261409 | 110 bulundu, 108 kayıtlı | 2 evrak eksik; evrak doğrulaması başarısız |
| 2020/364 | Evrak doğrulaması başarılı | Tahsilatlar içindeki bir tablonun boşluğu doğrulanamıyor; dosya bilgileri eksik |
| Diğer 17 kayıt | Evrak ve dosya bilgileri başarılı | Yeni canlı oturumda yeniden sınanmadı |

2020/364 içinde bazı tahsilat tabloları dolu ve doğrulanmış olsa da bir başka
tablonun kayıt sayısı belirsiz, okunan satır sayısı sıfırdır. Canlı görünüm
incelenmeden bunu "0 kayıt, eksiksiz" yapmak doğru olmaz.

## Belge içeriğinde arama

- **1.359 belge hazır**, 39 belge indeksleme hatasında.
- Hazır durumunda olup metin parçası bulunmayan belge: 0.
- 16 belge `.pdf` adıyla kayıtlı fakat dosya imzası PDF değil, XML;
  sınırlı başlık kontrolünde kök öğe `dava`. Bu bulgu yanlış isim/tür ile
  kaydetmeye işaret eder; yanlış dava içeriği indirildiğini tek başına kanıtlamaz.
  Kodda `web/public/jurisai-avukat/background.js:51` içindeki `fileNameFor`,
  tanınmayan içerik türünde `.pdf` varsayıyor (satır 71); incelenen 16 kaydın
  MIME türü `application/download`. Bu, gözlenen yanlış uzantı için güçlü bir
  neden adayıdır; bu turda gerçek indirme yanıtının başlıkları yeniden yakalanmadı.
- 16 arşiv, desteklenmeyen XML eki nedeniyle tamamen aranabilir sayılamıyor.
- 4 arşivde boş `ana_evrak.txt`, 2 arşivde iç içe ZIP, 1 arşivde EYP eki nedeniyle
  indeksleme başarısız.

Dolayısıyla "kaydedildi" ile "belge içeriği aranabilir" ayrı durumlar olarak
gösterilmelidir. Bu 39 belgenin içeriği mevcut aramaya dahil değildir.

## Sunucu, paket ve testler

- API sağlık kontrolü ve web UYAP sayfası: HTTP 200.
- Kaynak eklenti sürümü: **2.26.19**. İndirme ZIP'indeki 14 dosya, paketleme
  betiğinin satır sonu normalleştirmesi dikkate alındığında kaynakla eşleşiyor.
  Kullanıcının Chrome'unda etkin olan sürüm bu turda doğrulanamadı.
- Genel Python testleri: **1.210 geçti, 332 atlandı** (`PYTHONUTF8=1`).
  İlk koşuda alt süreç kodlama ortamından kaynaklanan 8 hata görüldü;
  UTF-8 ortamıyla yeniden çalıştırma temiz sonuçlandı.
- Web testleri: **269 geçti**. TypeScript ve hedefli ESLint kontrolleri başarılı.
- İzole veritabanı testleri: **78 geçti**. İlk koşudaki 9 hata test veritabanındaki
  iki eksik tablodan kaynaklandı. 048/049 migrationları yalnız açıkça seçilmiş
  `nhr_uyap_workflow_test` veritabanında, tablo yokluğu doğrulandıktan sonra
  uygulandı; canlı şema değiştirilmedi.
- Tam sentetik eklenti tarayıcı testleri: **108 geçti** (21 dakika 11 saniye).
  Yanlış dava kimliği, oturum kapanması, tüm yargı türleri ve liste sayfaları,
  geç yüklenen ağaç/ekler, büyük veya yarıda kesilen indirme, aktarımı durdurma,
  tekrar aktarım, bilgi sekmeleri ve belirsiz boş tablolar gibi senaryolar sınandı.

Test çıktıları yerel `.local/` altındaki `core-audit-20261008-utf8.xml`,
`uyap-db-audit-20261008-prepared.xml` ve `uyap-browser-audit-20261008.xml`
dosyalarında tutulur. Sentetik tarayıcı testleri sahte portal/veri ve ayrı
tarayıcı profili kullanır; gerçek UYAP kabul testinin yerini tutmaz.

## Yayın öncesi kapanması gerekenler

1. 2024/261409 için eksik iki evrakın kimliklerini canlı UYAP ağacından belirle,
   yalnız eksikleri yeniden aktar ve sunucudan kayıtlarını doğrula.
2. 2020/364 belirsiz tahsilat tablosunu canlı görünümle karşılaştır; yüklenmemiş
   tabloyu veya yardımcı görünümü gerçek boş tablo sanmadan düzelt.
3. Dosya türü/isim tespitini ve XML/EYP/iç içe arşiv ayrıştırma kapsamını düzelt;
   indeksleme hatalarını yeniden işle ve aranabilirlik kapsamını doğrula.
4. Güncel eklentiyle 21 dosyanın tamamını yeniden denetle; eksik/hatalı/işlenmemiş
   olmadan, evraksız dosyalar açıkça ayrılarak sonuç kaydedilsin. Tekrar çalıştırma
   mükerrer evrak oluşturmamalı, oturum kesintisi eksiksiz diye raporlanmamalı.

UYAP'ın erişilemezliği/oturum süresinin dolması engellenemeyebilir. Kabul ölçütü
bu durumları gizlememek, güvenli durmak ve eksikleri kayıpsız tamamlayabilmektir.

## 8 Ekim canlı denetim devamı

İlk denetimdeki tarayıcı engeli daha sonra aşıldı. Kullanıcının açık Chrome
oturumunda JurisAI ve UYAP birlikte sınandı; uygulama bağlantısında etkin
eklenti sürümü **v2.26.19** olarak görüldü. Bu bölüm ilk denetimden sonraki
kanıtları içerir; yukarıdaki tarayıcı erişimi sınırlaması bu devam denetimi
için geçerli değildir.

Uygulamanın listeleme düğmesi UYAP dosya sorgusunu açtı ve yargı türlerini
tarayarak **21 dosya** buldu: 2 ceza, 2 hukuk, 17 icra. Ardından **Yalnız
denetle (aktarmadan)** çalıştırıldı. Bu işlem evrak içeriği yüklemez; dosya
bilgilerini ve doğrulama raporunu JurisAI sunucusuna kaydeder. Kullanıcı
belgesi silinmedi, anahtar yenilenmedi ve uygulama kodu değiştirilmedi.

### Yeniden çalıştırılan kontroller

| Kontrol | Sonuç |
| --- | --- |
| Genel Python testleri | 1.210 geçti, 332 atlandı |
| Web testleri | 269 geçti |
| Genişletilmiş izole veritabanı testleri | 121 geçti |
| TypeScript ve hedefli ESLint | Başarılı |
| Üretim web derlemesi | Başarılı; dağıtım yapılmadı |
| `git diff --check` | Başarılı |
| Canlı arama ve UYAP durum uçlarına kimliksiz erişim | İkisi de HTTP 401 |
| Canlı uygulama tarayıcı konsolu | İncelenen hata günlüğünde 0 hata |

Genişletilmiş veritabanı testleri yalnız `nhr_uyap_workflow_test` içinde
çalıştırıldı. UYAP iş akışı/eşzamanlılık, token, kullanıcı izolasyonu,
mükerrerlik, belge RAG, içerik arama, organizasyon, indeksleme/OCR ve çöp
kutusu testleri kapsandı. Canlı kullanıcı verisinde test verisi üretilmedi.
Üretim derlemesindeki Vite yapılandırma uyarıları başarısızlık değildir.

Önceki tam sentetik tarayıcı koşusunun **108 başarılı testi**, kaynakları
değişmediği için bu devam denetiminde yeniden 21 dakika çalıştırılmadı;
yerine gerçek açık UYAP oturumu sınandı. Sentetik sonuçlar ile canlı
kabul sonucu birbirine karıştırılmamalıdır.

Yeni test çıktıları: `.local/core-audit-20261008-continuation.xml`,
`.local/uyap-db-audit-20261008-expanded.xml`. Önceki sentetik çıktı:
`.local/uyap-browser-audit-20261008.xml`.

### Tamamlanan canlı kabul sonucu

Denetim **8 Ekim 2026 17:13:20 Türkiye saati** itibarıyla tamamlandı;
sonuçların aynı zamanla veritabanına yazıldığı `nhr_runtime` rolü ve
kullanıcı kapsamındaki salt okunur sorguyla ayrıca doğrulandı.

| Ölçüm | Sonuç |
| --- | --- |
| Taranan dosya | 21 |
| Evrakları eksiksiz dosya | 18 |
| UYAP'ın evrak yok dediği dosya | 2 |
| Evrakı eksik dosya | 1 |
| Okunamayan / işlenmeyen dosya | 0 / 0 |
| Canlı ağaçta bulunan / kayıtla eşleşen evrak | 1.382 / 1.380 |
| Bu koşuda aktarılan evrak | 0 |
| Dosya bilgileri eksiksiz / kısmi | 20 / 1 |
| Dosya bilgisi kaydedilen dava | 21 |

İki eksik evrak **2024/261409** içindeki **07/10/2026 tarihli Kapalı
E-Tebliğ Mazbatası** kayıtlarıdır. Uygulamanın tek dosya seçim ekranında
78 asıl + 32 ek = 110 evrak bulundu, 108 kayıtlı gösterildi ve yalnız 2
yeni evrak otomatik seçildi. Aktarım düğmesine basılmadı. Bu iki evrakın
JurisAI'a yüklenmesi için ayrıca kullanıcı onayı istendi; bu rapor
yazılırken yanıt gelmedi. Aktarımın kendisi bu koşuda test edilmiş sayılmaz.

**2020/364** için canlı Tah./Red. Bilgileri görünümü ayrıca incelendi:
ana `tahsilatTable` 3 satır / 3 kayıt, `harcTable` 5 satır / 5 kayıt;
toplam tablosu 1 satırdır. Bunların yanında `display:none` durumunda
3 reddiyat detay tablosu vardır; satır sayıları 1, 1 ve 0. Sıfır satırlı
detayın düğmesi açıldığında ayrı "Detaylar" penceresinde yine 0 satır
görülür, fakat UYAP açık "0 kayıt"/boşluk bildirimi vermez. Güncel
okuyucu `content.js:1983` içinde pane altındaki tüm tabloları topladığı
için bu yardımcı detay da eksiksizlik değerlendirmesine girer. Uyarının
kaynağı canlı DOM ile böylece belirlendi; yalnız bu gözleme dayanarak
bilgileri zorla eksiksiz işaretlemek veya tablodaki veriyi silmek doğru
değildir. Yardımcı detayın anlamı ve boşluk kanıtı ayrı ele alınmalıdır.

Arayüzdeki **19 doğrulama kaydı**, toplam 21 dosyanın evrak bulunan
19'una aittir. `toServerItems` evraksız 2 dosyayı evrak doğrulama
kaydına göndermiyor (`web/src/lib/uyap-sync-all.ts:662`); ancak bu
dosyaların bilgi kayıtları dahil toplam 21 bilgi kaydı saklandı.
Dolayısıyla 19/21, bu koşuda yarıda kalma değildir; sayacın kapsamının
açık anlatılması gereken bir arayüz ayrımıdır.

Son fiziksel bütünlük kontrolü de yeniden yapıldı: aktif belge sayısı
**1.398**, mükerrer kimlik grubu **0**, eksik dosya/yanlış boyut/yanlış
SHA-256/eksik kimlik/bağlantısız belge **0**. Canlı denetim belge sayısını
değiştirmedi. Kanıt ekranı: `.local/uyap-audit-20261008-live.jpg`.

**Nihai karar: temel listeleme, ağaç karşılaştırması ve arama çalışıyor;
henüz hatasız aktarım ve tam aranabilirlik için yayın kabulü verilemez.**
Eksik iki evrakın aktarımı, yardımcı detayın doğru yorumlanması ve 39
indeksleme hatasının giderilmesi hâlâ açık maddelerdir.

### Gerçek arşivde içerik araması

- Arayüzde `icra emri` araması 22 sonuç verdi. `İCRA EMRİ` aynı 22 sonucu
  verdi; sonuçlardaki eşleşmeler vurgulandı.
- 2024/261409 dava filtresiyle yalnız ilgili dosyadan 2 sonuç döndü.
  Kapsam göstergesi o dosyanın 108 belgesinden 102 aranabilir, 6 okunamayan
  belge olduğunu doğru gösterdi.
- Bulunmayan sorgu 0 sonuç verdi; okunamayan belge uyarısı kaybolmadı.
- Tek karakterde en az 2 karakter uyarısı görüldü. Filtreleri temizleme
  çalıştı.
- İçerik araması sırasında başka sayfaya geçip UYAP sayfasına dönüldüğünde
  devam eden denetim korunuyordu. İşlem sürerken ikinci denetim/listeleme
  kontrolleri kapalıydı.
- `nhr_runtime` rolüyle, kullanıcı kapsamında ve salt okunur işlemde aynı
  sorgular sınandı: 22/22/0 sonuç, literal `%_` sorgusu 0 sonuç;
  yaklaşık 0,69–0,72 saniye. Belge içeriği rapora alınmadı.
- Toplam kapsam halen **1.398 kayıt / 1.359 aranabilir / 39 okunamayan /
  0 bekleyen**. Arama özelliğinin çalışması, 39 belgenin içeriğinin
  aranabildiği anlamına gelmez.

### Ayrıştırma sorunlarının küçük örneklerle tekrarı

`fileNameFor` saf fonksiyonu kaynak dosyadan alınarak çalıştırıldı:
uzantısız `Ek2` için hem `application/download` hem `application/xml`
yanıtı **`Ek2.pdf`** üretti; açık `fileExt: xml` verilince `Ek2.xml`
üretildi. Böylece tanınmayan türün PDF olarak adlandırılması kod düzeyinde
tekrarlandı. Tarihî indirme yanıtının tüm başlıkları yeniden yakalanmadı.

Sentetik içeriklerle `.pdf` isimli XML, doğrudan XML/EYP ve metinle beraber
XML içeren ZIP ayrıştırması tekrar sınandı. Mevcut ayrıştırıcı PDF imzası
uyuşmazlığını veya desteklenmeyen eki reddetti. Bunlar canlı evrak içeriği
değildir; dosya türü tespitinin ve arşiv ayrıştırma kapsamının düzeltilmesi
gerektiğini doğrulayan küçük tekrarlardır.

## Kullanıcı onayından sonraki düzeltmeler ve son durum

Bu bölüm yukarıdaki tarihî sonuçların yerine geçmez; sonraki uygulama ve
testleri kaydeder. Kullanıcının iki eksik evrakın mevcut JurisAI hesabına
aktarılması sorusuna verdiği onaydan sonra **yalnız bu iki evrak** aktarıldı.
Uygulama, 2024/261409 seçiminde 110 evraktan 108'ini kayıtlı buldu; iki yeni
07/10/2026 Kapalı E-Tebliğ Mazbatası seçiliydi. Sonuç penceresi **2 evrak
aktarıldı** gösterdi. Kullanıcı belgesi/hesabı silinmedi, anahtar yenilenmedi.
Kanıt: `.local/uyap-fix-two-imported-20261008.jpg`.

### Kapanan teknik sorunlar

- Eklenti kaynakları ve indirme paketi **v2.26.20** olarak hazırlandı.
  Bilinmeyen MIME'ın PDF sayılması kaldırıldı; XML/ZIP adlandırması, uzun
  adlarda uzantı korunması ve genel MIME altında gelen HTML giriş sayfasının
  reddi için regresyon testleri eklendi.
- XML/EYP ve iç içe ZIP desteği ortak boyut/sayı/derinlik bütçeleri ve güvenli
  yollarla eklendi. XML DTD/varlık/ikili veri sınırları test edildi. EYP imzası
  doğrulanmış sayılmaz; imza parçaları arama metni değildir. Eski yanlış
  uzantılı UYAP XML'leri, kaynak baytları değiştirilmeden yeniden indekslendi.
- Gerçek 2020/364 yardımcı reddiyat tablosu için dar yapısal boşluk kanıtı
  eklendi. Eşleşen düğme, tam şema ve kararlı/yüklenmeyen tablo koşulları
  birlikte aranır. Sunucu kanıtı ayrıca denetler; genel belirsiz boş tablolar
  başarılı sayılmaz. Bu yeni davranış **sentetik olarak doğrulandı; güncel
  eklentiyle canlı 2020/364 kabulü henüz yapılmadı**.
- Karma PDF ve çok sayfalı görüntüde okunamayan sayfanın sessizce atlanması
  engellendi. Çok kısa/boş OCR'da bir kez, kalan sayfa zaman bütçesiyle seyrek
  düzen denenir. Bu düzeltme gerçek arşivde varsayılan OCR'ın sıfır metin
  verdiği bir tarama sayfasını okuyabildi. OCR hâlâ hataya açıktır.
- Ayrıştırıcı sürümü indeks önbelleğine eklendi. Önceki saklı evrak sayacı
  “evraklı dosya” olarak netleştirildi; evraksız dosyalar toplamdan gizlenmez.

### Kaydedilmiş arşivin son doğrulaması

| Kontrol | Sonuç |
| --- | --- |
| Aktif UYAP kaydı / fiziksel dosya | 1.400 / 1.400 |
| 2024/261409 kayıt sayısı | 110 (önceden 108) |
| Eksik dosya / boyut / SHA-256 uyuşmazlığı | 0 / 0 / 0 |
| Mükerrer evrak kimlik grubu | 0 |
| Eksik kimlik / dava bağlantısı | 0 / 0 |
| Metin indeksi hazır / hatalı | 1.400 / 0 |
| 20 MB üzeri 11 arşivde görüntü sayfası kapsamı | 164 / 164 |

Onarım sonrası eksik 793 metin parçası vektörü de yalnız yapılandırılmış
loopback Ollama sağlayıcısıyla tamamlandı (45 belge). Haricî embedding
hizmetine belge gönderilmedi. Bu işlem, arama metni/vektör kapsamını sağlar;
üretilen hukuk cevaplarının doğruluğunu tek başına kanıtlamaz.

Başlangıçtaki 39 indeksleme hatası giderildi. Ardından daha sıkı sayfa
kapsamı kontrolü, 8 arşivde aynı tarama sayfasının eski OCR tarafından
atlandığını buldu. Bu sekiz arşiv güncel okuyucuyla yeniden işlendi; görüntü
sayfa kapsamı tekrar sıfır eksikle doğrulandı. Bu ölçüm bütün OCR metinlerinin
karakter karakter doğrulandığı veya tüm PDF sayfalarının bağımsız gözle
karşılaştırıldığı anlamına gelmez. Orijinal dosyaların SHA-256 değerleri
yeniden kontrol edildi; değiştirilmedi.

Gerçek arayüzde daha önce PDF sanılan XML'lere yönelik içerik araması
30 belge eşleşmesi ve vurgulama üretti. Bu sorgu, son büyük OCR işi bitmeden
1.399 hazır belge üzerinde sınandı; son 1.400 hazır sayısı kullanıcı
kapsamındaki veritabanı sorgusuyla ayrıca doğrulandı. Ardından son arayüz
kontrolünde **1.400 / 1.400 aranabilir** görüldü; olmayan sınama ifadesi
0 sonuç verdi. Kanıt: `.local/uyap-search-coverage-20261008.jpg`.
Test sorgusu temizlenip UYAP bağlantı sayfasına dönüldü. Yeni kaynak belgeler
başka hizmete gönderilmedi; metin onarımı yerel olarak yapıldı.

1.400 fiziksel kayıt ile son canlı ağacın 1.382 evrakı aynı ölçüm değildir:
farklı evrak kimlikli 18 tarihî kayıt korunmuştur. Bunlar mükerrer ilan edilip
silinmedi. Önceki 108/110 denetim raporu yeni aktarım üzerine otomatik yeni
kabul raporuna dönüşmez; yeniden canlı denetim gerekir.

### Düzeltme sonrası test kanıtları

| Kontrol | Sonuç |
| --- | --- |
| Genel Python, son OCR düzeltmesi dahil | 1.234 geçti, 339 atlandı |
| Genişletilmiş izole PostgreSQL/RLS testleri | 126 geçti |
| Web testleri | 269 geçti |
| TypeScript / hedefli ESLint / üretim derlemesi | Başarılı |
| API yeniden başlatma ve sağlık | `ok`, veritabanı bağlı |
| `git diff --check` | Başarılı |

Tam sentetik Chromium koşusu **111 geçti, 1 başarısız** (21 dakika 44 saniye).
Tek başarısızlık sürüm ping testidir: koşu başlatıldıktan sonra manifest
2.26.19'dan 2.26.20'ye yükseltildiği için fixture'ın yüklediği sürüm ile
testin diskten okuduğu sürüm farklıydı. Sürüm sabitlendikten sonraki hedefli
ping tekrarı geçti. Dört yeni indirme/boşluk kanıtı regresyonu da ayrı koşuda
geçti. Bu, tam grubun tek seferde temiz geçtiği diye raporlanmaz.
Son v2.26.20 hedefli koşusu da **4 geçti, 108 seçilmedi**: sürüm ping'i,
genel MIME altında XML/HTML ayrımı ve eşleşen/eşleşmeyen yardımcı tablo.
Çıktı `.local/uyap-fix-final-browser-20261008.xml` altında.

Son genel çıktı `.local/uyap-final-core-ocr-20261008.xml`, izole DB çıktısı
`.local/uyap-fix-db-20261008.xml` (son OCR sonrası tekrar da 126 geçti:
`.local/uyap-db-final-ocr-20261008.xml`), tam tarayıcı çıktısı
`.local/uyap-fix-browser-20261008.xml` altında. Testler gerçek UYAP yerine
sentetik portal kullanır; canlı kabulün yerine geçmez.

### Açık son kabul adımı

Chrome'daki etkin eklenti bu bölüm yazılırken **v2.26.19** olarak görüldü.
Kullanıcıdan indirme düğmesindeki **v2.26.20** paketini yüklemesi ve iki
sekmeyi yenilemesi istendi. Chrome iç uzantı sayfası kontrol aracı tarafından
erişilebilir olmadığı için güncelleme kullanıcıya bırakıldı. Anahtar yenileme,
yeni izin verme veya belge silme gerekmez.

Güncellemeden sonra 21 dosya **Yalnız denetle (aktarmadan)** ile tekrar
karşılaştırılmalı: iki eksik evrakın eşleşmesi, 2020/364 bilgileri, evraksız
iki dosya ve kaydedilen son rapor birlikte doğrulanmalıdır. Bu yapılana kadar
**“tümü hatasız, yayına hazır” kabulü verilmemiştir**. UYAP oturum/erişim
kesintilerinde yanlış başarı üretmeden durma ve yeniden deneme davranışı
yayın koşuludur; dış portal için sıfır kesinti garantisi verilemez.

## v2.26.20 canlı denetiminin kaydedilmiş sonucu — 9 Ekim kontrolü

Kullanıcı güncellediğini bildirdikten sonra uygulamadaki etkin bağlantı
**v2.26.20** olarak doğrulandı. Listeleme 21 dosyayı (2 ceza, 2 hukuk,
17 icra) tamamladı. **Yalnız denetle (aktarmadan)** başlatıldı; ilk dosyanın
bilgi sekmelerinde ilerlediği görüldü. Sonraki yanıt kesintisinden sonra
9 Ekim'de Chrome bağlantısı yeniden kuruldu. Uygulama `/auth` giriş
sayfasındaydı; kimlik doğrulama yapılmadı ve yeni aktarım başlatılmadı.

Sonuç kullanıcı kapsamındaki `nhr_runtime` salt okunur sorgularıyla
doğrulandı. Evrak denetimi **8 Ekim 2026 18:35:53 Türkiye saati** ile
tek grup halinde kaydedilmiş:

| Ölçüm | Kaydedilmiş sonuç |
| --- | --- |
| Evraklı dosya denetimi | 19 / 19 eksiksiz |
| UYAP ağacında bulunan evrak | 1.382 |
| Eksik evrak | 0 |
| Dosya bilgileri | 21 / 21 eksiksiz |
| Daha önce eksik 2024/261409 | 110 bulundu, 0 eksik, eksiksiz |
| Daha önce kısmi 2020/364 bilgileri | Eksiksiz, 18:31:06'da kaydedilmiş |

21 dosyanın bilgi kayıtları 18:25:58–18:35:53 aralığında güncellenmiş.
2020/364'ün bu kaydında `uyap_static_reddiyat_detail` kanıt alanı yok;
dolayısıyla özel fallback dalının bu canlı koşuda kullanıldığı iddia edilmez.
Kaydedilen genel bilgi eksiksizliği sonucu başarılıdır; özel dal için
pozitif/negatif sentetik test kanıtları ayrıca geçerlidir.

9 Ekim arşiv kontrolü de temiz: 1.400 fiziksel dosyada boyut/SHA-256,
kimlik/bağlantı hatası ve mükerrer evrak kimliği 0; 1.400 metin indeksi
hazır, 3.942 parçanın vektörsüz sayısı 0. Büyük arşivlerde görüntü sayfa
kapsamı yine 164/164. API sağlıklı ve veritabanına bağlı.

**Sınırlama:** Tarayıcı yeniden bağlandığında tamamlanmış koşunun tam
arayüz raporu artık erişilebilir değildi. Sunucu evraksız dosyaları ve
sıfır evrakla okunamayan dosyaları evrak denetim tablosuna kaydetmiyor;
bu nedenle yalnız 19 satırdan, kalan iki dosyanın bu koşudaki evraksız
sonucunu veya bütün koşunun hata/işlenmedi sayaçlarını bağımsız yeniden
üretmek mümkün değil. İki dosyanın evraksız olduğu önceki canlı raporda
görülmüştü; bunların dosya bilgileri bu koşuda da eksiksiz kaydedilmiş.

**Karar:** Mevcut hesabın 19 evraklı dosyası için yeni sürümün kaydedilmiş
canlı evrak kabulü başarılı; önceki iki eksik evrak ve kısmi bilgi sorunu
bu kapsamda kapanmıştır. Tüm kullanıcılar/portal türleri veya dış portal
kesintileri için “sıfır hata” garantisi verilmez. Tam 21 dosyalık son raporu
yeniden görmek/kanıtlamak gerekirse kullanıcı girişinden sonra yeni yalnız
denetim gerekir; bu kontrolde giriş veya yeni denetim yapılmadı.

## Tam 21 dosyalık canlı kabul — 9 Ekim 2026, 10:50:58

Kullanıcı girişini tamamladıktan sonra Chrome'daki mevcut JurisAI ve UYAP
Vatandaş Portalı sekmeleri kullanıldı. Etkin eklenti **v2.26.20** olarak
görüldü. Yeni evrak yüklemeden **Yalnız denetle (aktarmadan)** çalıştırıldı.
Bu bölüm yukarıdaki tarihsel gözlemleri değiştirmez; yeni koşunun sonucudur.

### İlk denemedeki sorun ve kurtarma

İlk denemede 2024/2000 eşleşti; 2024/124 ve ardından 2020/1204 dosya
penceresi açılamadı/kimliği doğrulanamadı. Koşu kullanıcı düğmesiyle
güvenli durduruldu: 1 tamamlandı, 2 okunamadı, 18 işlenmedi; 0 evrak
aktarıldı. Bu başarısız deneme başarı sayılmadı.

2020/1204 için portalın normal **Dosya Görüntüle** düğmesiyle doğrudan
deneme de görünür pencere açmadı. DOM'daki dosya modalı `display:none`,
`aria-hidden=false` durumundaydı; görünür hata bildirimi yoktu. Bu bir
takılmış sayfa durumuna işaret eder, fakat tek başına kesin kök neden
kanıtı değildir. UYAP sayfası yenilendi, dosya sorgulama sayfasının geri
geldiği doğrulandı, JurisAI'da liste yeniden okundu ve 21 dosyanın denetimi
baştan çalıştırıldı. Anahtar yenileme, izin değişikliği, belge silme veya
yeni evrak aktarımı yapılmadı. Kurtarma manuel sayfa yenilemesiydi;
otomatik kurtarma düzeltmesi yapılmış gibi raporlanmaz.

### Temiz sayfadaki tam koşunun sonucu

Tam rapor arayüzden 21 satırıyla okundu. Sonuç mesajı:

> Bütün dosyalar eksiksiz: 21 dosya, 1382 evrak JurisAI'da doğrulandı
> (2 dosyada UYAP evrak göstermiyor).

Dosya bilgileri 21/21 eksiksiz okundu ve kaydedildi. Yeni gönderilen evrak
0; eksik evrak 0; okunamayan ve işlenmemiş dosya 0. İki evraksız sonuç
bu kez yalnız eski kayıttan değil, tamamlanan canlı arayüz raporundan
doğrulandı.

| Dosya | Eşleşen / bulunan evrak | UYAP ana sayı | Bilgi sekmesi | Bilgiler |
| --- | ---: | ---: | ---: | --- |
| 2024/2000 | 5/5 | 4 | 2 | Eksiksiz, kaydedildi |
| 2024/124 | 350/350 | 98 | 3 | Eksiksiz, kaydedildi |
| 2020/1204 | 80/80 | 73 | 3 | Eksiksiz, kaydedildi |
| 2019/1157 | 79/79 | 72 | 4 | Eksiksiz, kaydedildi |
| 2025/197080 | 123/123 | 83 | 5 | Eksiksiz, kaydedildi |
| 2025/151719 | 121/121 | 80 | 5 | Eksiksiz, kaydedildi |
| 2025/148157 | 129/129 | 88 | 5 | Eksiksiz, kaydedildi |
| 2025/130725 | 14/14 | 14 | 5 | Eksiksiz, kaydedildi |
| 2024/83057 | 47/47 | 41 | 4 | Eksiksiz, kaydedildi |
| 2024/269672 | 79/79 | 56 | 5 | Eksiksiz, kaydedildi |
| 2024/261409 | 110/110 | 78 | 5 | Eksiksiz, kaydedildi |
| 2024/195537 | 81/81 | 57 | 5 | Eksiksiz, kaydedildi |
| 2020/364 | 28/28 | 27 | 4 | Eksiksiz, kaydedildi |
| 2020/2802 | 15/15 | 12 | 5 | Eksiksiz, kaydedildi |
| 2024/3231 | 94/94 | 44 | 4 | Eksiksiz, kaydedildi |
| 2018/4890 | 4/4 | 4 | 4 | Eksiksiz, kaydedildi |
| 2017/23319 | 13/13 | 13 | 4 | Eksiksiz, kaydedildi |
| 2011/9698 | 7/7 | 7 | 5 | Eksiksiz, kaydedildi |
| 2010/8096 | Evrak yok | — | 5 | Eksiksiz, kaydedildi |
| 2009/17135 | Evrak yok | — | 5 | Eksiksiz, kaydedildi |
| 2009/11547 | 3/3 | 3 | 4 | Eksiksiz, kaydedildi |

### Bağımsız sunucu ve disk doğrulaması

Kullanıcı kapsamındaki `nhr_runtime` salt okunur sorgusu son evrak grubunun
**9 Ekim 2026 10:50:58 Türkiye saati** ile kaydedildiğini doğruladı:
19 evraklı dosyanın 19'u eksiksiz, toplam 1.382 evrak, 0 eksik.
21 bilgi kaydı 10:41:49–10:50:58 aralığında yenilendi ve tamamı eksiksiz.
2024/261409 110/110; 2020/364 bilgileri 10:46:37'de eksiksiz kaydedilmiş.
Özel statik reddiyat fallback kanıt alanı bu kayıtta yine 0; o dalın bu
canlı koşuda kullanıldığı iddia edilmez.

Koşu öncesi ve sonrası fiziksel belge sayısı **1.400** kaldı. Boyut,
SHA-256, eksik dosya, eksik kimlik, bağlantısız belge ve mükerrer kimlik
hatası 0. İndeksler 1.400/1.400 hazır; 3.942 parçanın vektörsüz sayısı 0.
11 büyük arşivde 38 görüntü üyesi / 164 sayfa kapsamı tam. Mevcut ağaçta
görünmeyen 18 tarihsel belge korunmuştur; 1.400 ile 1.382 farkı yeni
mükerrer aktarım diye yorumlanmaz.

API sağlık kontrolü `ok`, veritabanı bağlı; `git diff --check` başarılı.
Bu turda uygulama/eklenti kaynak kodu değiştirilmedi; önceki testler
yeniden çalışmış gibi sunulmaz. Sonuç ekranı açık bırakıldı; ekran kanıtı
`.local/uyap-live-acceptance-20261009.jpg` altında.

**Kabul:** Bu hesabın erişebildiği 21 dosyanın temiz sayfadaki canlı
denetimi tam geçti. Önceki iki eksik evrak, kısmi dosya bilgisi ve iki
evraksız dosyanın açık sonuç kanıtı bu kapsamda tamamlandı. İlk denemedeki
takılmış sayfa davranışı nedeniyle tüm oturumlar için kesintisiz/sıfır
hata veya genel yayın hazır garantisi verilmez; otomatik güvenli kurtarma
ve tam koşu raporunun kalıcı saklanması ayrıca iyileştirme konularıdır.

## 9 Ekim devamı — v2.26.21 uygulaması

Önceki bölümde kalan iki yazılım işi uygulandı: güvenli, sınırlı salt okunur
sayfa toparlanması ve evraksız/hatalı/işlenmeyen dosyaları da içeren kalıcı
tam koşu geçmişi. Yeni tablo yerel uygulama ve izole test veritabanına
eklemeli migration ile kuruldu; mevcut belge ve hesaplara dokunulmadı.
API yalnız kendi doğrulanmış yerel süreci yeniden başlatılarak güncellendi;
sağlık `ok`, veritabanı bağlı ve yeni uç nokta OpenAPI'de mevcut.

### Bu turda tamamlanan kanıtlar

* Yeni toparlanma Chromium testi tek başına geçti: yanlış iş kimliği ve
  açık textarea reddedildi; sayfa yenilenmediği ölçüldü. Doğru aynı sekme
  yenilendi, aynı dosya yeniden açılıp kimliği doğrulandı, sık yenileme
  sınırı çalıştı ve belge yüklemesi yapılmadı.
* Rapor doğrulama testleri; tüm beş sonuç türü, bekleyen dosyalar, yarım
  koşu, eski revizyonun reddi, bitmiş kaydın değiştirilememesi, sunucu
  kanıtı yetersiz başarıyı düşürme, yabancı hesap SQL SELECT/UPDATE/DELETE
  izolasyonu, UUID çakışması, KVKK dışa aktarma ve hesap purge kapsamı.
* Arayüz testleri; geçmişin açılır-kapanır gösterimi, yarım koşu uyarısı,
  okunamayan ile boş geçmişin ayrımı, metin kaçışlama, hesap değişiminde
  eski raporun görünmemesi ve eski koşunun yeni hesaba yazmaması.
* TypeScript kontrolü ve üretim derlemesi geçti. Değişen web dosyalarında
  ESLint hata yok; AuthProvider'ın mevcut hook/fast-refresh uyarıları kaldı.

İzole DB'nin ilk geniş koşusu, eksik `047_account_security.sql` kurulumu
yüzünden dört hesap testinde durdu. Yalnız test DB'sine ön koşul uygulandı.
Yeni purge testinde paylaşılan fixture'ın eski kullanıcı bağlamı temizlendi;
üretim kodunun yetki denetimi gevşetilmedi. Ardından 88 test birlikte geçti.

### Son yerel sonuçlar ve v2.26.22 çekim kilidi

* Tam Chromium eklenti regresyonu v2.26.21'de **113/113** geçti
  (23 dakika 2 saniye). Gerçek UYAP değil, gerçek Chromium içinde sentetik
  portal/indirme/yükleme uçları kullanıldı.
* Ardından toparlanma onayı-yenileme arasındaki manuel çekim/dosya açma/prob
  başlangıcı da kilitlendi; güncellemenin meşgul sorgusu kilidi görür.
  Bu son dar değişiklik v2.26.22 olarak paketlendi. İlgili altı Chromium
  senaryosu v2.26.22'de yeniden **6/6** geçti (1 dakika 44 saniye):
  toparlanma, manuel çekim, anahtarsız diske indirme, açık pencere yokluğu,
  sürerken durdurma ve meşgulken güncelleme. 113 testin tamamı bu son
  küçük değişiklikten sonra yeniden çalıştırılmış gibi sunulmaz.
* Web testleri **293/293**; tam Python paketi **1.286 geçti / 353 atlandı**.
  Atlamalar opt-in tarayıcı/veritabanı testlerini de içerir; bunlar ayrıca
  yukarıdaki Chromium ve aşağıdaki izole DB koşularında sınandı.
* İzole UYAP + hesap/veri dışa aktarma testleri son ek önbellek kontrolüyle
  **89/89** geçti. Kullanıcı belgeleri silinmedi; test yazımları rollback.
* TypeScript, üretim derlemesi, üç eklenti JS dosyasının sözdizimi ve
  `git diff --check` geçti. İndirilebilir zip kaynakla aynı paket kontrolüne
  dahil. ESLint hatası yok; AuthProvider'ın iki mevcut uyarısı duruyor.
* API son kodla yeniden başlatıldı. İlk kontrol başlangıç tamamlanmadan
  bağlantı alamadı; sonraki kontrol sağlık `ok`, DB `connected`, yeni rapor
  uç noktası mevcut, anonim geçmiş isteği 401, web sayfası 200 doğruladı.
* Tam koşu listeyi veren sekmeye ilk dosyadan sabitlenir; sonraki açık
  UYAP sekmesine geçilmez. Hatalı ağaç okumasından sonra bilgi okuması da
  aynı sekmede kalır. Bu sekme kimliği geçmişe gönderilmez.

### Canlı son kabul sınırı

Bilgisayar kullanım becerisiyle mevcut kullanıcı Chrome'una bağlanma
denendi; araç `windows sandbox failed: helper_unknown_error: setup refresh
had errors` ile başlatılamadı. Oturum sıfırlanıp bir kez tekrar denendi,
aynı hata tekrarlandı. Bu turda canlı sayfaya tıklanmadı; anahtar
yenilenmedi, belge silinmedi veya yüklenmedi. v2.26.21 güncellemesi ve
bu sürümde 21 dosyalık son canlı koşu henüz kanıtlanmış değildir.
Önceki v2.26.20 canlı sonucu yeni sürümün sonucu diye sunulmaz. Kullanıcı
v2.26.21'i güncellediğini bildirdi; bunun ardından son manuel çekim kilidi
v2.26.22 paketine alındı. v2.26.22'nin kullanıcı Chrome'unda yüklendiği
ve yeni 21 dosyalık canlı kabul koşusu tamamlandığı iddia edilmez.

## 9 Ekim akşamı — kullanıcı raporu ve kontrollü yeniden aktarım hazırlığı

Kullanıcı 21/21 dosyanın evrakları ve bilgileri birlikte doğrulanıp
kaydedildiğini bildiren rapor paylaştı: 19 evraklı, 2 evraksız dosya;
1.382/1.382 kayıtlı evrak; eksik/hatalı/işlenmeyen 0; yeni gönderim 0.
Bu kullanıcı tarafından sağlanan canlı denetim raporudur; bu turda bağımsız
Chrome gözlemi veya yeni indirme/yükleme kanıtı sayılmaz. Raporda eklenti
sürümü yazmadığından yüklü sürüm hakkında sonuç çıkarılmaz.

Kullanıcı, önce yedek ardından küçük bir dosyada yeniden aktarım ve
mükerrerlik testi planını onayladı. Hazırlıkta:

* API sağlık `ok`, veritabanı `connected`, UYAP web sayfası 200.
* Yerel yedek hedefi `nhr-legal-ai-db` / `nhr_legal_ai` doğrulandı.
  Hukuk korpusu dışarıda bırakıldı. Doğrulama için kullanılacak
  `jurisai_restore_check` veritabanının başlangıçta mevcut olmadığı
  salt okunur kontrol edildi; mevcut bir veritabanı ezilmedi.
* `scripts/backup_user_data.py --verify` yeni, önceden mevcut olmayan
  `data/backups/uyap-reimport-20261009-7b075e3c/` altında çalıştırıldı.
  `jurisai-20261009-213918` yedeğinde 35 tablo / 18.410 satır ve
  1.413 yüklenmiş dosya bulunuyor. Dump geçici veritabanına geri yüklendi,
  tüm satır sayıları eşleşti; arşiv ve dosya özetleri doğrulandı.
  Geçici doğrulama DB'si betik tarafından kaldırıldı. Eski yedek silinmedi;
  yeni yedek Git dışında yerel proje dizininde tutuluyor.
* Tarayıcı kontrolü yine `windows sandbox failed: helper_unknown_error:
  setup refresh had errors` ile başlatılamadı. Belgelenmiş bilgisayar
  kullanım başlatması ve kernel sıfırlaması sonrası tekrar da başarısız.
  Açık hesabın güncel UI kimliği ve aktarım erişimi doğrulanamadığı için
  hiçbir belge silinmedi; yeni aktarım veya tekrar çekme testi başlatılmadı.

Sonuç: yedekleme/geri yükleme hazırlığı başarılı; canlı küçük dosya
sil–yeniden aktar–mükerrerlik kabul testi kontrol bağlantısı nedeniyle açık.

## 9 Ekim 23:32 — tam yeniden aktarım ön kontrolü

Kullanıcı tüm UYAP belgelerini sıfırlayıp yeniden indirmeyi istedi.
Chrome kontrol bağlantısı bu kez çalıştı. JurisAI hesap menüsündeki
hesap kimliği, sahibin RLS bağlamındaki `users` kaydıyla eşleştirildi.
UYAP oturumu açık; JurisAI ekranı eklenti v2.26.22 bildiriyor. Uygulamadaki
"Listeyi yenile" ile canlı liste yeniden okundu; tarama tamamlandı ve
21 dosya listelendi. Bu gözlem yeni belge indirme/yükleme kanıtı değildir.

Salt okunur disk/DB ön kontrolü: 1.400 aktif UYAP belgesi; mükerrer evrak
kimliği, kayıp dosya, boyut veya SHA-256 uyuşmazlığı, eksik kimlik ve
bağlanmamış dava sayısı 0. Bu hesabın aktif UYAP dışı belgesi yok.
Son ağaçtaki 1.382 evraktan farklı olarak 18 tarihsel belge korunuyor;
UYAP'tan tekrar indirilebilecekleri garanti edilemez.

Yeni yedek:
`data/backups/uyap-reset-preflight-20261009-2335/jurisai-20261009-233203/`.
35 tablo / 18.410 satır, 1.413 fiziksel dosya. `--verify` ile geçici
veritabanına geri yükleme, satır sayıları, dump/arşiv özetleri ve ZIP
bütünlüğü doğrulandı. Geçici DB önceden mevcut değildi; eski yedekler
ve mevcut belgeler silinmedi.

Test için önerilen sıfırlama, yalnız bu hesabın 1.400 UYAP belgesini
mevcut geri alınabilir çöp kutusu akışıyla pasifleştirmek; hesap, dava,
müvekkil, kaynak korpusu ve UYAP'taki asıllar korunacak. Çöpteki belgeler
aktif listelerden, aramadan ve yineleme kontrolünden çıkar; yeniden
indirme/yükleme gerektirir. Normal çöp saklama süresi 30 gündür.
Silme işlemi öncesi son kapsam onayı bekleniyor; bu ön kontrolde belge
silinmedi, çöpe taşınmadı veya yeniden aktarılmadı.

## 9 Ekim 23:42 — onaylı tam UYAP belge sıfırlaması

Kullanıcı geri alınabilir çöp yerine "hepsini yok et" diyerek kalıcı
belge silmesini açıkça istedi. Aynı hesap menüsü yeniden doğrulandı.
İşlem öncesi 1.400 hedef dosyanın tamamı, yeni yedekteki arşiv üyesiyle
SHA-256 düzeyinde karşılaştırıldı: tamamı eşleşti. Toplam 833.738.154 bayt.
Hedefler yalnız `uploads/office/<doğrulanmış-sahip>/` altında çözümlendi;
paylaşılan/hedef dışı yol olmadığı kontrol edildi. İlk arşiv üyesi kontrolü
ZIP kökündeki `office/` önekini hesaba katmadığı için güvenli biçimde durdu;
henüz silme yapılmadan bu ön kontrol düzeltildi ve tüm üyeler doğrulandı.

`.local/reset-uyap-documents-20261009.py` önce salt okunur envanteri kaydetti,
sonra aynı envanter parmak iziyle `--execute` çalıştı. `nhr_runtime` ve
sahibin RLS bağlamı dışında belge yazımı yok; mevcut `trash_document` ve
`delete_forever` akışı, her belge için denetim kaydıyla kullanıldı.

Sonuç: **1.400 kalıcı silindi; kalan UYAP belgesi, eski hedef fiziksel
dosya ve türetilmiş indeks belgesi 0**. 1.400 kalıcı silme denetim kaydı,
istek `1ab6fa8c-d84f-4d32-b253-f8db6bd84dfc`. Kaynaklara bağlı sohbet
cevabı bulunmadığından temizlenen cevap 0. Hesap, 22 dava ve 1 müvekkil
kaydı korundu; korunacak kayıtların tüm satır parmak izleri eşleşti.
Uygulamanın belge ekranında "Henüz belge yok" ve boş çöp kutusu görüldü.
Yedekler korunuyor; UYAP portalındaki asıllara ve korpusa dokunulmadı.

Bu bölüm sıfırlama kanıtıdır; yeniden indirme sonucu değildir.

### Temiz aktarım başlatıldı — sonuç henüz açık

23:43:33'te canlı JurisAI arayüzündeki "Tüm dosyaları aktar (21 dosya)"
ve "Aktarımı başlat" onayıyla yeni koşu başlatıldı:
`8dcbc091-b286-429c-b0d2-3dc28094977d`, `verify_only=false`.
İlk dosya 2024/2000 için 5/5 evrakın **5'i yeni gönderildi** ve son
doğrulama eksiksiz geçti. Ardından 350 evraklı 2024/124 işlenmeye başladı.
23:50:09 ölçümünde 69 yeni belge / 69 hazır indeks; eski kayıt UUID'leri
0, yeni koşunun tamamlanan dosyalarında raporlanan hata/eksik 0.
Bu, kalan 20 dosyanın başarılı olduğu veya tüm aktarımın tamamlandığı
anlamına gelmez; henüz yeniden indirme kabul sonucu verilmez.

`.local/monitor-uyap-reimport-20261009.py --watch` salt okunur RLS
bağlamında bu belirli koşuyu 30 saniyede bir izliyor. Sayaçlar, dava bazlı
belge sayıları, indeks durumları, tamamlanan dosyaların hata/eksik
raporları `.local/uyap-reimport-progress-20261009.jsonl` içine yazılıyor.
Belge içeriği/oturum/anahtar kaydedilmez. Gözlemci koşu bittiğinde veya
başlangıcından itibaren en çok 3 saat sonra durur; aktarımı kendisi
başlatmaz, durdurmaz veya yeniden denemez. Sonradan tam koşu raporu,
dosya hash/boyutları, mükerrerlik ve içerik indeksleri ayrıca denetlenmeli.

Arayüzde 34/350 sırasında kısa süre ilerleme görünmedi; portalın kendi
eklenti durum satırlarında çekimin devam ettiği ve DB'de yeni kayıtların
arttığı görüldü. Dosya sayfasından dönüşte bir SPA link tıklaması etkisiz
kaldı; aktarıma başlamadan önce gözlenen UYAP rota adresi doğrudan açıldı.
Bu geçişte React'in henüz bağlanmamış bileşene state güncelleme uyarısı
konsolda görüldü; gerçek aktarım hatası olarak sınıflandırılmadı.

## 10 Ekim — temiz koşu sonucu ve hız darboğazlarının giderilmesi

Önceki bölümün açık koşusu 10 Ekim **01:29:17**'de bitti: 5 dosya
eksiksiz, 5 eksik, 3 okunamadı, 8 işlenmedi. Başlangıç 9 Ekim 23:43:33;
yaklaşık 106 dakika. İşlenen ağaçlarda 1.027 evrak bulundu, **967 yeni
belge kaydedildi / 967 indeks hazır**, 60 evrak eksikti. İşlenmeyen
dosyalar bu sayılarda sıfır evraklı sayılmaz. Eski 1.400 hedef UUID'sinden
kalan yok; kayıtlar gerçekten temiz yeniden indirmeden geldi. Üç ardışık
okunamayan dosyadan sonra koşu güvenli biçimde durdu. Bu sonuç kabul
başarısı değil; 9 Ekim'deki eski 21/21 denetimiyle karıştırılmamalıdır.

Salt okunur zaman çizelgesi, üç Ankara Banka Alacakları dosyasının her
birinin yaklaşık 16–17 dakika sürdüğünü gösterdi. Her birinde 15 KEP HTML
belgesi, İstanbul 2024/269672'de 9 KEP HTML belgesi giriş/hata sayfası
sanılıp tekrar deneniyordu. Büyük ZIP indirmelerinin veri akışı da
8–21,6 MB civarında kesilmiş, 45 saniyelik hareketsizlikten sonra yeniden
başlamıştı. 2024/261409 toparlanma korumasında, 2024/195537 ve 2020/364
dosya açma/kimlik doğrulamada durdu. Son iki sorun sınıfı henüz çözülmedi;
güvenlik korumaları kaldırılmadı.

Kullanıcının hızlandırma talebi için **v2.26.23** hazırlandı:

* Başarılı evrakın işlem süresi güvenli başlangıç aralığına dahil;
  üstüne sabit bekleme yeniden eklenmiyor. Hata/backoff tam korunuyor,
  eşzamanlı portal tıklaması yok, son evrakta bekleme yok.
* Uygun ağaç türü + üç dar pasif KEP şablonu birlikte doğrulanıyor.
  Giriş/hata/etkin HTML reddi sürüyor; özgün baytlar korunuyor.
* Yedekteki 105 HTML (29 makbuz, 32 KEP paketi, 16 KEP iletisi,
  28 tam metin PTT bildirimi) üretim tanıyıcısıyla 105/105 tanındı.
  Özel içerik test deposuna eklenmedi, bu kontrolde canlı belge yüklenmedi.
* 100 × 700 ms doğrudan işin sentetik modeli 120 sn → 70 sn; gerçek
  portal kazancı henüz ölçülmedi. Daha fazla CPU kullanımı veya kontrolsüz
  paralellik yerine boşa bekleme/yeniden deneme giderildi.

Doğrulama: 311/311 Node arayüz testi (9 hız/tanıma testi dahil), typecheck,
üretim build'i, betik sözdizimi ve ZIP/kaynak eşleşmesi geçti. API/belge
regresyonu 45 geçti, 32 DB testi bağlantı tanımlı olmadığı için atlandı.
Seçili Chromium regresyonunda 17 test geçti; eski sabit bekleme beklentili
bir test başarısız oldu. Beklenti yeni minimum başlangıç aralığını ve
azalan beklemeyi ölçmek üzere güncellendi; tek başına tekrar geçti
(18 seçili senaryo başarılı). Daha önceki dar taramada bir seçici
zaman aşımı tek başına tekrarda geçti; yeni KEP gerçek aktarım ve sahte
giriş reddi senaryoları da geçti. Tüm Chromium testleri bu sürümde yeniden
koşturulmuş değildir.

Yeni paket oluşturuldu; canlı JurisAI ekranında hâlâ **v2.26.22** görüldü.
Kullanıcıdan v2.26.23'e güncellemesi istendi. Bu turda yeni silme, bağlantı
anahtarı yenileme veya canlı aktarım yapılmadı; 967 mevcut belge korundu.
Güncelleme sonrası yalnız kalanların aktarımı ve son tam denetim gerekli.

### 10 Ekim 14:15 — v2.26.23 canlı kalanları tamamlama koşusu

Kullanıcı güncellediğini bildirdi; canlı JurisAI ekranında v2.26.23 ve
açık UYAP oturumu doğrulandı. Dosya Sorgulama menüsü açılıp uygulamadan
yeniden listeleme tamamlandı: 21 dosya. Mevcut 967 belge / 967 hazır indeks
korunarak "Tüm dosyaları aktar" akışı 14:15:11'de başlatıldı:
`d1b9fb0e-8ad6-4fae-8474-2dc12491b7fe`.
Kayıtlı evraklar atlanır; yalnız eksikler yeni indirmeye girer. İlk dosya
2024/2000 5/5 doğrulandı, gönderilen 0. İkinci dosyada 344/350 kayıtlı,
yalnız altı eksik evrak indirmeye alındı. Bu başlangıç kanıtıdır;
sonuç tamamlanmadan kabul başarısı değildir.

`.local/monitor-uyap-speed-20261010.py --run <bu-koşu> --watch` yalnız
sahibin RLS bağlamında sayaç/indeks durumu ve rapor kontrol noktalarını
30 saniyede bir izler; içerik okumaz, aktarımı veya veriyi değiştirmez.
Bu turda silme ve bağlantı anahtarı yenileme yapılmadı.

#### Koşu sonucu, canlı KEP testi ve v2.26.24

Toplu koşu 14:19:26'da operatör tarafından durduruldu; aynı altı başarısız
evrakın tekrar denenmesi önlendi. Son kayıt `finished=true`, `aborted=true`:
bir dosya eksiksiz, ikinci dosya iptal/hata durumunda, 19 dosya işlenmedi.
Bu koşuda yeni belge gönderilmedi. İkinci dosyanın altı eksik evrakından
Ek 41 indirmesinde UYAP 6,9 MB'dan sonra 45 saniye veri göndermedi;
Ek 75 / Ek 1 / Ek 2 / Ek 23 yanıtlarında gerçek vekâlet pulu makbuzu
işaretleri vardı, ancak ağaç türü/adı yalnız `Ek` olduğu için tanıyıcı
bunları reddetti. Son evrak iptal edildi; altı evrağın tümü hakkında aynı
sebep varmış gibi sonuç çıkarılmaz. Büyük ZIP akışı sorunu çözülmedi.

Ardından uygulama içinden yalnız 2025/197080 dosyasındaki 15 eksik KEP
evrakı seçilip aktarıldı. Tarayıcı sonuç okumasında bağlantı zaman aşımı
oldu; aynı aktarım yeniden başlatılmadı. Sahibin RLS bağlamında salt okunur
kontrol, bu dosyada **108 → 123**, toplamda **967 → 982** belge ve
**982 hazır indeks** gösterdi (14:29 kontrolü). 982 dosyanın fiziksel
varlığı, boyutu ve SHA-256 değeri doğrulandı: eksik/bozuk dosya, eksik
evrak kimliği, ilişkisiz belge veya çift evrak kimliği grubu yok.
Bu, 15 KEP'in kaydedildiği kanıtıdır; 21 dosyanın son tam ağaç denetimi
veya gerçek portal hız karşılaştırması değildir.

**v2.26.24** makbuz tanımasını dar kapsamlı genişletir: türü tam `Ek`,
adı tam `Ek` veya `Ek <sayı>` olan ekler ancak mevcut vekâlet pulu
makbuzu/Adalet Bakanlığı/Makbuz No alanları ve pasif HTML kontrollerinin
tamamını geçerse kabul edilir. Giriş/hata sayfası, etkin HTML, ilgisiz tür
ve belirsiz ad kabul edilmez; özgün baytlar korunur. Yetkiler, zaman
aşımı ve ZIP indirme akışı değişmedi.

Doğrulama: 312/312 Node testi (ZIP/kaynak eşleşmesi dahil), typecheck,
betik sözdizimi ve `git diff --check` geçti. Gerçek Chromium'da seçili
makbuz/KEP/zamanlama regresyonu **8 geçti, 109 seçilmedi**; iki yeni
senaryo Ek 75 makbuzunun özgün baytlarla tek yüklemesini ve aynı metadata
altındaki giriş HTML'inin yüklenmemesini sınar. İlk Node koşusu paket
yenilenmediği için ZIP/kaynak eşleşmesinde kaldı; paket yeniden üretildikten
sonraki tam koşu geçti. Tüm Chromium paketi yeniden koşulmuş değildir.

Chrome kontrol bağlantısı `Debugger unattached` durumuna geçti; seçili
tarayıcıdaki mevcut sekmeye yeniden bağlanma da sonuç vermedi. Yeni
transfer/anahtar yenileme/silme yapılmadan UYAP ve JurisAI sekmeleri devam
için korundu. Canlı kurulu sürüm v2.26.23; v2.26.24 paketi hazır, yeni
makbuz düzeltmesinin canlı kabulü ve kalan dosyaların aktarımı bekliyor.

### 10 Ekim 14:53 — v2.26.24 canlı kabulü ve v2.26.25 toparlanması

Chrome kontrolü yeniden çalıştı; canlı v2.26.24 görüldü. Eklentide anahtar
eksikti; kullanıcı anahtarı kendisi yenileyip bağlantı onayını tamamladı.
Anahtar çıktılarda gizlendi; hiçbir belge silinmedi. Yalnız eksikler seçildi:

* 2024/124: beş makbuz hatasız geldi, 344 → 349 / 350. Ortalama indirme
  0,1 sn, yükleme 0,1 sn, bekleme 0,3 sn. Ardından yalnız büyük Ek 41 ZIP
  denendi: 49,1 MB'dan sonra 45 sn veri gelmedi; kayıt oluşmadı. Önceki
  6,9 MB kesintisiyle aynı boy değil. Kök neden bu gözlemle kesinleşmedi.
* 2025/151719: 15 KEP hatasız geldi, 106 → 121. Ortalama indirme 0,1 sn,
  yükleme 0,1 sn, bekleme 0,2 sn.
* 2025/148157: 15 KEP hatasız geldi, 114 → 129. Ortalama indirme 0,1 sn,
  yükleme 0,4 sn, bekleme 0,0 sn.
* 2024/269672: sekiz KEP geldi, bir Ek 1 reddedildi; 70 → 78 / 79.
  Yanıt KEP iletisi şablonuydu, ancak metadata yalnız Ek olduğundan
  KEP kapısını geçemedi. Son ek henüz canlıda aktarılmadı.

Toplam **982 → 1025 belge / 1025 hazır indeks**, 43 yeni belge. Sahibin
RLS bağlamında 1025 fiziksel dosyanın varlığı, boyutu ve SHA-256'sı
doğrulandı: eksik/bozuk dosya, eksik evrak kimliği, ilişkisiz belge veya
çift kimlik grubu yok. Bu tüm 21 dosyanın güncel son ağaç denetimi değildir;
eski toplu rapor değiştirilmedi. Kabul ekranları `.local/` altında tutuluyor.

**v2.26.25** değişiklikleri:

* İndirme `cache: no-store` kullanır. Sıkıştırılmamış Content-Length
  varsa alınan boyla karşılaştırılır; kesik/fazla gövde ve beklenmeyen
  206 başarılı sayılmaz.
* Kesik akış yalnız güçlü ETag varsa en fazla iki kez Range / If-Range
  ile sürdürülür. 206, aynı güçlü ETag, URL, MIME, doğru başlangıç/son/toplam
  ve varsa parça boyu birlikte doğrulanır. Range'i yok sayan 200 veya
  değişen belge/aralık/sıkıştırma birleştirilmez. ETag yoksa devam yoktur;
  mevcut sınırlı tam yeniden deneme korunur. Gerçek UYAP ZIP'inde bu
  başlıkların desteklendiği henüz ölçülmedi.
* Yalnız etkin indirme sırasında 20 sn aralıklı getPlatformInfo çağrısı
  MV3 boşta kapanma riskini azaltır; başarı/hata sonunda temizlenir.
  İçerik/kimlik göndermez, izin eklemez. Normal 45 sn ayarıyla 8 MB
  alındıktan sonra hareketsizlik payı 120 sn olur. İlk yanıt/küçük evrak,
  özel kısa ayar ve iki saat toplam sınır değişmez; sınırsız bekleme yoktur.
* Türü tam Ek, adı tam Ek / Ek <sayı> olan KEP ekleri ancak mevcut dar
  pasif KEP şablonu/alanları ve giriş/hata reddiyle kabul edilir.
  Keyfi HTML kabul edilmez; özgün baytlar korunur.

Doğrulama: **336/336 Node**, typecheck, üretim build'i, betik sözdizimi ve ZIP/kaynak
eşleşmesi geçti. Seçili Chromium regresyonu **11 geçti, 110 seçilmedi**:
kesik HTTPS akışının kalan baytlarla tam yüklemesi, değişen ETag'in reddi,
yavaş/büyük/kesik gövdeler, Ek adlı KEP/makbuzlar ve etkin/giriş HTML reddi.
İlk HTTPS fikstürü Chrome öneki okumadan kapandığı için iki test kaldı;
önekten sonra 200 ms bırakılınca odaklı iki test ve son 11 testlik koşu
geçti. Node harness'ındaki eksik sabit de düzeltildi. API/arşiv/rapor/bilgi
regresyonu **30 geçti, 10 DB testi bağlantı olmadığı için atlandı**.
Tüm Chromium paketi bu sürümde yeniden koşulmadı.

Apilex'in [platform sayfası](https://www.apilex.ai/tr/platform) ve
[resmî eklenti kaydı](https://chromewebstore.google.com/detail/apilex-ai-for-legal/eifhpjccnfcdaaeomidagonmkllcoogk)
UYAP için Chrome eklentisini anlatıyor. Kamuya açık aktarım API dokümanı
bulunamadı; özel uç noktaları denenmedi. Bizim akış bilinen UYAP belge
adreslerini kullanıcının açık oturumuyla kullanır. Çalışan ömrü için
[Chrome belgesi](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle)
esas alındı; bu, canlı ZIP kesintisinin kanıtlanmış nedeni değildir.

v2.26.25 paketi hazır; kullanıcıdan güncelleme istendi. Büyük ZIP, son
Ek 1 ve kalan dosyaların aktarımı/son tam denetimi henüz tamamlanmadı.
**Yayın kabulü veya sıfır hata garantisi verilmez.**

### 10 Ekim — v2.26.25 canlı kabulü (devam ediyor)

Chrome'da v2.26.25 ve 21 dosyalık güncel liste doğrulandı. Mevcut 1025
belge korunarak yalnız eksikler seçildi; anahtar yenilenmedi, veri silinmedi.

* 2024/269672'deki son `Ek 1` KEP eki başarıyla aktarıldı: yakalama 0,0 sn,
  indirme 0,2 sn, yükleme 0,1 sn. Dosya 79 belgeye ulaştı.
* 2024/261409 için 110/110 yeni evrak başarıyla aktarıldı. Ekranın bildirdiği
  evrak başına ortalamalar: yakalama 0,0 sn, indirme 0,2 sn, yükleme 0,6 sn,
  bekleme 0,2 sn. Bunlar dosya açma/tarama dahil uçtan uca süre değildir.
* RLS kapsamında mevcut kullanıcının 1136 belgesi fiziksel dosya, boyut,
  SHA-256, UYAP kimliği ve dava bağlantısı açısından denetlendi: hata ve
  mükerrer kimlik grubu sıfır. 1136 belgenin indeks durumu `ready`.
* **Büyük ZIP hâlâ başarısız:** 2024/124'ün ilişkili 2022/608 Talimat
  Dosyasındaki `Gelen Talimat İsteği Yazısı 28/12/2022 / Ek 41` aktarımında
  22,5 MB geldikten sonra 120 sn veri gelmedi. Eksik dosya kaydedilmedi;
  2024/124 hâlâ 349/350. Yeni zaman aşımı/heartbeat/Range düzenlemesi bu
  canlı belgeyi çözmüş sayılmaz. Yanıttaki güçlü ETag / Range desteği henüz
  gözlenmedi; kesintinin kesin nedeni saptanmış değildir.
* UYAP'ın yerel Kaydet menüsüyle karşılaştırma denenirken tarayıcı denetimi
  bağlantısı kesildi. Bir indirme tamamlandığı doğrulanmadı; bu deneme ZIP
  başarısı veya portal arızasının kanıtı olarak kullanılamaz.

Tam izole Chromium regresyonu: **121 geçti, 1233,58 sn**. Yeniden çalıştırılan
API/arşiv/rapor/bilgi testleri: **30 geçti, 10 DB testi atlandı**
(`NHR_TEST_DATABASE_URL` yok), bir Starlette/httpx kullanımdan kaldırma uyarısı.
Seçili testlerle tam regresyon sonucu artık birbirinden ayrı kaydedildi.

Kanıt ekranları yerelde `.local/uyap-v25-kep-success-20261010.png`,
`.local/uyap-v25-110-success-20261010.png` ve
`.local/uyap-v25-zip-failure-20261010.png` altında. Belge içerikleri ve
anahtarlar bu rapora eklenmedi. Kalan dosyaların aktarımı ve yeni tam 21 dosya
denetimi tamamlanmadan yayın kabulü verilmez.

#### 10 Ekim 16:07 — kalan normal evraklar tamamlandı

Tek dosyalı canlı akışta ayrıca 2024/195537: 81, 2020/364: 28,
2020/2802: 15, 2024/3231: 94, 2018/4890: 4, 2017/23319: 13,
2011/9698: 7 ve 2009/11547: 3 evrak hatasız kaydedildi. Her dosyada
sonuç ekranı başarıyı doğruladı. 2020/364 aktarımı sırasında tarayıcı
denetim çağrısı zaman aşımına uğradı; işlem körlemesine tekrarlanmadı.
Önce sunucudaki 28 kayıt, bağlantı toparlanınca ekrandaki 28 başarı görüldü.
Bu kesinti uygulamanın aktarım hatasıyla karıştırılmadı.

Mevcut 1025 belge korunarak bu canlı kabulde **356 yeni belge** eklendi:
toplam **1381 belge / 1381 hazır indeks**. Sahibin RLS bağlamındaki yeniden
fiziksel denetimde eksik dosya, boyut/SHA-256 uyuşmazlığı, eksik UYAP
kimliği, dava bağlantısı eksiği ve mükerrer evrak kimliği grubu **sıfır**.
Bu kontrol bir elektronik imza doğrulaması değildir.

Güncel 21 dosyalık **yalnız denetim** 16:06'da başlatıldı
(`09ec8883-b4b2-485e-a611-acbf2fefa2a0`); yeni evrak göndermez. İlk iki
ağaçta 2024/2000 için 5/5, 2024/124 için 349/350 görüldü. Son rapor henüz
tamamlanmadı; tarihli eski 21/21 raporu güncel kabul yerine kullanılmaz.

Ek doğrulamalar: **348/348 Node**, typecheck ve üretim build'i geçti.
Genişletilmiş UYAP/XML/rapor/dosya bilgisi/aktarım/arşiv/organizasyon/içerik
arama Python koşusu ayrı geçici klasörle **84 geçti, 42 atlandı**
(`NHR_TEST_DATABASE_URL` yok), bir Starlette/httpx uyarısı. İlk koşunun
dört hatası ürün assertion'ı değil, Windows'un eski `.local/tmp/pytest`
temizliğini engelleyen `WinError 5` setup hatasıydı; eski klasör silinmeden
ve izinler değiştirilmeden yeni benzersiz test klasörü kullanıldı.

Büyük Ek 41 için doğal UYAP Kaydet indirmesinin tamamlandığı hâlâ
doğrulanmadı; kullanıcıdan indirme durumu/boyutu istendi. Kesintiyi UYAP'a
veya eklentiye kesin olarak atfetmek için yeterli kanıt yok.

#### 10 Ekim 16:15:48 — yeni tam denetim bitti

v2.26.25 ile 16:06:21–16:15:48 arasındaki yalnız denetim, durdurulmadan
tamamlandı ve hesabın rapor geçmişine kaydedildi (aynı koşu UUID'si,
revision 23, `finished=true`, `verify_only=true`, `aborted=false`).

* **21 dosya:** 18 evraklı dosyada evraklar eksiksiz, 2 dosya evraksız,
  1 dosyada tek evrak eksik; 0 okunamadı, 0 işlenmedi.
* **1382 bulundu / 1381 kayıtlı / 1 eksik / 0 gönderildi.** Denetim yeni
  belge aktarmadı; önceki tek dosyalı aktarımlar mükerrerlenmedi.
* **Dosya bilgileri 21/21 eksiksiz okundu ve kaydedildi.** Daha önce sorun
  veren 2020/364 tahsilat/reddiyat bilgileri bu güncel koşuda da eksiksiz.
* Tek evrak eksiği 2024/124'te **349/350**: yukarıda tanımlanan büyük Ek 41.
  2024/261409 **110/110**, 2024/195537 **81/81**.
* 2010/8096 ve 2009/17135 için portalın evrak yok yanıtı ayrıca doğrulandı;
  okuma hatası sıfır evrak gibi raporlanmadı.
* Son RLS gözleminde **1381 aktif UYAP belgesi / 1381 hazır indeks**;
  fiziksel bütünlük denetiminin sıfır hata sonucu değişmedi (bu denetimde
  belge baytları eklenmedi/değişmedi).

Güncel ekran kanıtı `.local/uyap-v25-final-audit-20261010.png` incelendi;
anahtar veya belge içeriği görünmüyor. Canlı aktarım/denetim işi artık
çalışmıyor; JurisAI sonuç sekmesi ve kullanılan UYAP sekmesi devam için
korunuyor. **1382/1382 kabulü yoktur; büyük ZIP kesintisi çözülmeden yayın
hazır kararı verilmez.**

#### Kullanıcının doğal indirme karşılaştırması

Kullanıcı, aynı 2024/124 büyük Ek 41 için UYAP'ın kendi **Kaydet**
indirmesinin de durmuş/başarısız olduğunu bildirdi. Bu kullanıcı gözlemidir;
Chrome'un hata kodu, alınan/toplam boy ve güçlü doğrulayıcı başlıkları
henüz görülmedi. Kesinti yalnız JurisAI yolunda görünmüyor; ancak bu bulgu
tek başına UYAP sunucusu, ağ veya tarayıcı kaynaklı kesin kök neden vermez.
Mevcut 1381 belge korunur; kesik ZIP tamamlanmış veya aktarılmış sayılmaz.

#### 10 Ekim 16:48 — hata ayrımı ve v2.26.26

Kullanıcının açıkça paylaştığı `Hata.html` yerel artefaktı 437 baytlık
bir UYAP hata sayfasıdır: `Hata Oluştu / Hata Mesajı: / Doğrulama
hatası.Lütfen tekrar deneyiniz.` ZIP değildir. Artefaktta evrak kimliği
ve istek adresi bulunmadığından yalnız Ek 41'e ait olduğu doğrulanamaz;
bu yanıt tek başına oturumun kapandığını da kanıtlamaz.

v2.26.25 ile yalnız eksik Ek 41'in yeni canlı aktarımı tekrar denendi:
**46,0 MB geldikten sonra 120 sn yeni veri gelmedi**, aktarım sıfır başarı
ve bir hata ile bitti. Kesik dosya kaydedilmedi. 16:48:43 RLS gözlemi
**1381 aktif belge / 1381 hazır indeks**, 2024/124 için **349/350**
sonucunu doğruladı. Doğal Kaydet karşılaştırmasındaki tarayıcı denetim
çağrısı zaman aşımı, indirme sonucu olarak yorumlanmadı.

v2.26.26 paketindeki değişiklikler:

* Dar UYAP doğrulama hatası şablonu, genel HTML/oturum hatalarından ayrıldı.
  `UYAP_VALIDATION_FAILED` sonucu aynı reddedilmiş adresle yeniden
  denenmez; dosyayı yeniden açıp evrakı yeniden seçme gereği bildirilir.
  Bu hata, gerçek pasif makbuz/KEP HTML istisnasını kullanamaz. Gerçek
  bir belgede bu kelimelerin alıntılanması tek başına ret sebebi değildir.
* Büyük indirmede gelen/toplam MB, toplam boyut bilinmiyorsa bu durum,
  son veriden beri geçen süre ve güvenli sürdürme sayısı canlı işin
  ilerlemesine eklendi. Yalnız aynı sekme ve aynı çalışan aktarım işi
  görür; adres, ETag, çerez, anahtar veya belge içeriği iletilmez.
* Kaynak ve dağıtım ZIP'i eşleştirildi; yeni tarayıcı izni veya uç nokta
  eklenmedi. Bu düzenleme tek başına büyük ZIP kesintisinin çözümü değildir.

Güncel yerel doğrulama: **360/360 Node testi**; ayrıca seçili izole gerçek
Chromium regresyonunda **9 geçti, 113 seçilmedi** (75,43 sn). Bu sayı tam
Chromium suite'i değildir; önceki 121 testlik tam koşu v2.26.25'e aittir.
Seçili koşu doğrulama sayfasının yüklenmemesini/tekrarlanmamasını, gerçek
KEP/makbuz istisnalarını, yavaş akış ve güvenli sürdürme davranışlarını,
köprü komutlarını ve yalnız seçili evrakların aktarılmasını içerir.

Ekran kanıtı `.local/uyap-ek41-fresh-failure-20261010.png`.
Chrome son gözlemde hâlâ v2.26.25 olduğundan v2.26.26 canlı kabulü henüz
yapılmadı; kullanıcıdan güncelleyip iki sekmeyi yenilemesi istendi.
**1382/1382 tamamlanması ve yayın hazırlığı iddia edilmez.**

#### 10 Ekim 17:12 — v2.26.26 canlı tek evrak testi

Kullanıcının güncellemesinden sonra JurisAI ekranında **v2.26.26** görüldü.
2024/124 ağacı yeniden okundu: **98 asıl + 252 ek = 350**, 349 kayıtlı,
yalnız Ek 41 seçildi. Yeni canlı aktarımda MB göstergesi ve hareketsizlik
süresi gerçekten çalıştı: **19,4 MB (toplam boyut bildirilmedi)**,
ardından 26, 76 ve ekran kanıtında 84 sn yeni veri olmadığı görüldü.
**120 sn veri gelmeyince sıfır aktarım / bir hata** ile bitti.
v2.26.26 büyük ZIP kesintisini çözmüş değildir.

UYAP'ın kendi sağ tık → Kaydet işlemi de denendi. Üst üste iki görünür
menü saptanınca portal yenilenip 2024/124 → 2022/608 → Gelen Talimat
İsteği Yazısı 28/12/2022 → Ek 41 yolu normal UI ile yeniden açıldı.
Bu temiz durumda **tek görünür Kaydet** seçeneğine basıldı; tarayıcı
aracının 45 sn'lik indirme tamamlanma bekleyicisi sonuç alamadı.
Bu zaman aşımı doğal indirmenin başarısız olduğu veya hiç başlamadığı
anlamına gelmez; dosya yolu/tamamlanma doğrulanmadı. Kullanıcıdan bu
son doğal indirmenin Chrome'da görünen durum ve boyutu istendi.
Portalın bazı JavaScript hataları da görüldü; kesintinin kök nedeni
olarak sunulmadı. Kesin ETag/Range desteği hâlâ gözlenmiş değildir.

17:12:21 RLS gözlemi **1381 aktif belge / 1381 hazır indeks**, 2024/124
için 349 kayıt sonucunu koruyor. Yeni anahtar üretilmedi, belge silinmedi.
Önceki tam rapor tarihli bir denetimdir; bu tek evrak denemesi onu
güncel tam denetim veya 21/21 başarı olarak değiştirmez.

Yeni izole gerçek Chromium testi de **1 geçti, 122 seçilmedi (18,58 sn)**:
gerçek içerik betiğindeki iş kimliği, worker'daki akış baytları ve web
köprüsü üzerinden yalnız aynı canlı işe ulaşan ilerleme uçtan uca
doğrulandı. İş bitince eski indirme fazı gösterilmez; tek seçili belge
yalnız bir kez yüklenir. Node'un önceki 360/360 sonucu değişmedi.
Bu seçili koşular tam Chromium suite'i olarak raporlanmaz.

İncelenen kanıtlar: `.local/uyap-v26-live-progress-20261010.png` ve
`.local/uyap-v26-ek41-result-20261010.png`; anahtar veya belge içeriği yok.

#### 10 Ekim — geçici Kaydet hatasının yanlış sınıflandırılması, v2.26.27

Kullanıcı son doğal Kaydet denemesinin “Hata.html veya başarısız”
göründüğünü bildirdi. Bu kullanıcı gözlemidir; yeni indirmenin tam hata
kodu, bayt sayısı ve Ek 41 kimliği bağımsız olarak doğrulanmış değildir.
Önceden paylaşılan 437 baytlık Hata.html bu yeni denemenin kesin sonucu
olarak sunulmaz. Doğal indirme kesintisinin kök nedeni hâlâ açık.

Kodda ayrıca yeniden üretilebilir bir hata bulundu: doğrudan önizleme
“çok büyük” dediğinde Kaydet indirmesi geçici olarak kesilirse, sarmalayan
hata mesajı `retryable` niteliğini kaybediyordu. İçerik betiği yalnız
“önizlemede vermiyor” metnine bakıp bunu kalıcı evrak reddi sayıyor,
normal tıklamayla taze istek yakalama yolunu atlıyordu. Yeni regresyon
testi düzeltme öncesinde bu nitelik kaybıyla başarısız oldu.

v2.26.27 geçici kesinti/AbortError/HTTP 429/5xx niteliğini sarmalayıcı ve
worker yanıtı boyunca korur. İçerik betiği yapılandırılmış geçici hata
niteliğine öncelik verir; tıklama yakalanamazsa da nitelik kaybolmaz.
Doğrudan yol geçici hatayla başarısız olursa **bir normal UI tıklaması** ile taze istek
yakalanır; yakalanmış isteğin sınırlı yeniden denemesi korunur. Kalıcı
ret, doğrulama reddi, eksik bayt ve pasif HTML kontrolleri gevşetilmez;
sınırsız deneme veya doğrulanmamış parça birleştirme eklenmez.

İzole gerçek Chromium regresyonu, doğrudan önizleme reddi → Kaydet
kesintisi → bir normal tıklama → tam belgenin tek yüklemesini doğruladı.
Geniş koşuda **121 geçti / 3 başarısız** sonucu ayrıca incelendi: türetilmiş
Kaydet adresinin 404 hatası, asıl HTML/giriş sayfası hatasını örtüyordu.
Asıl hata bağlamı korunacak şekilde düzeltildi. Sonrasında bu üç senaryo,
geçerli KEP ve yeni tıklama regresyonu birlikte **5 geçti / 119 seçilmedi**.
Son düzeltmeyle tam Chromium grubu yeniden çalıştırıldı:
**124/124 geçti (1246,44 sn / 20 dk 46 sn)**. Bu koşu yalnız sahte UYAP
ve sahte API içeren izole gerçek Chromium ortamındadır; canlı UYAP'ın
her durumda hatasız yanıt vereceği garantisi değildir.

Güncel **366/366 Node testi**, typecheck, JavaScript sözdizimi ve dağıtım
ZIP/kaynak eşleşmesi geçti. UYAP/API/belge/arşiv/içerik arama regresyonu
**81 geçti, 43 atlandı**; atlanan veritabanı testleri için ayrı test DB
bağlantısı tanımlı değil. Üretim veritabanı test DB'si olarak kullanılmadı.

18:43:40 RLS gözlemi **1381 aktif belge / 1381 hazır indeks**, 2024/124
için 349 kayıt sonucunu koruyor. 18:42 canlı UI hâlâ **v2.26.26** gösterdi;
v2.26.27 paketi hazır ve kullanıcıdan güncellemesi istendi. Ekran kanıtı:
`.local/uyap-v27-update-needed-20261010.png`. UYAP Dosya Sorgulama ekranı
hazırlandı. Belge silinmedi, anahtar yenilenmedi, yeni aktarım başlatılmadı.
Yeni sürümle Ek 41 canlı kabulü yapılmadan **1382/1382 veya yayın hazır**
iddiası yoktur.

18:49 fiziksel bütünlük denetimi 1381 belgenin dosya mevcudiyeti, boyut,
SHA-256, UYAP kimliği ve dava bağlantısını yeniden kontrol etti: tüm hata
sayaçları sıfır, mükerrer UYAP kimliği grubu sıfır. Bu, elektronik imza
özgünlüğü veya UYAP'taki henüz indirilemeyen belgenin bütünlüğü kanıtı değildir.

19:04 canlı kontrolünde çalışan aktarım işi yoktu. JurisAI sayfası
yenilendikten sonra da **v2.26.26** görüldü; dolayısıyla v2.26.27'nin
canlı kabul testi başlatılmadı. Kullanıcıdan güncellemesi istenen paket,
son kaynak/ZIP eşleşmesi kontrolünü geçti. Yeni anahtar üretilmedi,
1381 mevcut belge silinmedi. Güncellemeden sonra yalnız eksik Ek 41
test edilecek; eski tam rapor yeni bir denetim sonucu gibi sunulmayacak.

#### 10 Ekim 20:18–20:27 — v2.26.27 canlı Ek 41 kabul sonucu

Kullanıcı güncellediğini bildirdikten sonra JurisAI ekranında **v2.26.27**
doğrulandı. Açık UYAP oturumundan 21 dosya listelendi; yalnız 2024/124
seçildi. Yeni evrak taraması **98 asıl + 252 ek = 350**, **349 kayıtlı**
sonucunu verdi. DOM'daki seçili kutular da kontrol edildi: yalnız
`2022/608 / Gelen Talimat İsteği Yazısı 28/12/2022 / Ek 41` seçiliydi.
Toplu aktarım, belge silme veya anahtar yenileme yapılmadı.

Tek evrak işinde üç ayrı tam indirme denemesi görüldü: **18,4 MB**,
**28,4 MB**, ardından **33,7 MB**. Aralarda ilerleme yeniden yanıt
başlıklarını bekleme durumuna döndü; bayt sayısı yeni denemede sıfırdan
ilerledi. Bu, önceki sürümde atlanan sınırlı yeniden deneme yolunun
canlıda artık işletildiğini destekler; tam belgenin alındığını kanıtlamaz.
Toplam boyut hiçbir denemede bildirilmedi. Sonuç **0 aktarım / 1 hata**:
son deneme 33,7 MB'dan sonra 120 sn yeni veri gelmemesiyle durdu.
**v2.26.27 büyük ZIP kesintisini çözmedi; canlı kabul başarısızdır.**

20:27:16 RLS gözlemi **1381 aktif belge / 1381 hazır indeks** ve
2024/124 için **349 kayıt** sonucunu korudu. Aynı anda yeniden yapılan
fiziksel dosya, boyut, SHA-256, UYAP kimliği ve dava bağlantısı denetiminin
tüm hata sayaçları sıfır; mükerrer kimlik grubu sıfır. Kesik ZIP kayıtlı
belge sayılmadı. Bunlar mevcut kayıtların fiziksel bütünlüğü kontrolleridir;
elektronik imza özgünlüğü denetimi değildir.

Son tam denetim hâlâ 16:15 tarihli **1382 bulunan / 1381 kayıtlı /
1 eksik** raporudur; bu tek evrak denemesi yeni tam denetim değildir.
Güçlü ETag/Range desteği veya kesintinin UYAP/ağ/eklenti kaynaklı olduğu
kesinleştirilmedi. Yeni bir sürümün hazırlanması ya da bekleme süresinin
artırılması tek başına kabul kriteri sayılmaz. Sıradaki tanı ihtiyacı,
aynı Ek 41'in doğal indirmesiyle uzantı indirmesinin yanıt/bağlantı
sonuçlarını güvenli biçimde karşılaştırıp kesintinin kaynağını ayırmaktır.

İncelenen ekran kanıtları: `.local/uyap-v27-live-progress-20261010.png`
ve `.local/uyap-v27-ek41-result-20261010.png`. Bağlantı anahtarı veya
belge içeriği içermez. Sonuç penceresi ve UYAP sekmesi sonraki tanı
için korundu; çalışan aktarım işi kalmadı.

#### 10 Ekim 20:31 sonrası — kapsamlı yerel kabul, etkin iptal düzeltmesi (v2.26.28)

Kod incelemesinde yeni somut hata: içerik betiği `pulling.stop` bayrağını
değiştiriyor ama worker'daki devam eden `fetch` isteğini kesmiyordu.
Kullanıcı durdurduktan sonra 120 sn hareketsizlik sınırı beklenebilir,
hatta o evrakın indirmesi ve yüklemesi devam edebilirdi. Önceden iptal
edilmiş iş, gövde ortasında iptal ve başlık beklerken iptal için eklenen
üç regresyon testi düzeltmeden önce **3/3 başarısız** oldu.

v2.26.28 değişikliği:

- İş başına `AbortController`: indirme, güvenli Range devamı, kayıtlı
  evrak sorgusu ve JurisAI yüklemesi aynı iptal sinyaline bağlı.
- Yeniden deneme ve evraklar arası bekleme de kesilebilir. İptal
  `UYAP_CANCELLED` olarak ayrılır; hata sayacı veya taze tıklama/yeniden
  deneme tetiklemez. BEGIN cevabından önceki durdurma yarışı da ele alınır.
- İptal/bitiş yalnız sahip sekme, frame ve iş kimliğiyle uygulanır;
  başka işin geç gelen END'i aktif aktarımı silemez. İkinci BEGIN aktif
  işi veya onun iptal denetleyicisini ezemez. UYAP dışı kaynaklardan
  bu çekim komutları reddedilir; yeni tarayıcı izni eklenmez.
- Sekme kapanması/ana sayfa gezinmesi sahipsiz isteği iptal eder.
  Önizleme iframe yüklenmesi yanlış iptal oluşturmaz.
- Sunucuda iptalden önce tamamlanmış bir kayıt geri alınmaz; sonraki
  `/known` ve denetim gerçek kayıt durumunu belirler. Belge silme yok.

Yerel doğrulamalar (aynı kaynak ve v2.26.28 dağıtım ZIP'i):

- Node: **374/374**; yeni 3 indirme iptali + 5 iş/sekme/bekleme testi dahil.
- Tip kontrolü, üretim derlemesi, UYAP TypeScript dosyalarının ESLint
  kontrolü, JavaScript sözdizimi ve kaynak/ZIP eşleşmesi geçti.
- Genel Python koşusu: 1377 geçti, opt-in DB/tarayıcı nedeniyle 369 atlandı.
- Sonra **yalnız bu çalışma için** `127.0.0.1:55434` üzerinde yerel
  `pgvector/pgvector:0.8.6-pg16` ile ayrı `nhr_uyap_acceptance_test`
  veritabanı kuruldu. Canlı `.env`/5433 veritabanı kullanılmadı.
  Tüm `database/init` şemalarıyla genel koşu **1621 geçti / 125 atlandı**
  (29,77 sn): 124 opt-in Chromium senaryosu ve test korpusunda olmayan
  5302 m.14 kaydı. Yani DB/RLS testleri bu kez çalıştı, sessizce atlanmadı.
  İki uyarı: test-client deprecation ve kasıtlı bozuk TIFF fixture'ının EXIF'i.
  Oluşturulan konteyner kimliği doğrulanıp testten sonra kaldırıldı;
  asıl kullanıcı konteynerleri çalışır durumda bırakıldı.
- Seçili Chromium: **9/9** (72,96 sn). Hem web köprüsü hem popup ile
  `/known`, başlık, gövde ve upload aşamalarında iptal beş saniye içinde
  bitti; yeni evrak isteği/yükleme veya hata sayacı oluşmadı. Önceki
  sıra-durdurma testi de geçti.
- Ek yaşam döngüsü Chromium: **3/3** (26,01 sn): iframe yüklenmesi,
  ana sekme yenileme ve sekme kapatma.
- Tam Chromium regresyonu: **132/132 geçti (1315,73 sn / 21 dk 55 sn)**.
  Tam koşu başladıktan sonra eklenen yukarıdaki üç yaşam döngüsü senaryosu
  ayrıca aynı v2.26.28 kaynaklarıyla çalıştırıldı. Böylece **135 farklı
  Chromium senaryosu** geçti; 9 testlik hedef koşu bu toplamı şişirmek
  için yeniden sayılmadı. Node + Python/DB + Chromium toplamı **2130
  farklı geçen test**; test korpusunda olmayan 5302 m.14 testi atlandı.

20:52:04 RLS/fiziksel kontrolü: **1381 aktif belge / 1381 hazır indeks**,
2024/124 için 349 kayıt; eksik dosya, boyut, SHA-256, kimlik, dava bağı
ve mükerrer kimlik grubu hata sayaçları sıfır. Bu kayıt denetimi yeni
bir UYAP tam taraması değildir; son tam canlı rapor hâlâ 16:15 tarihli
**1382 bulunan / 1381 kayıtlı / 1 eksik** sonucudur. 20:57 API sağlık
kontrolü `ok / database connected`; web manifest'i v2.26.28 sunuyor.

Canlı doğal Kaydet karşılaştırması sırasında tarayıcı kontrol bağlantısı
kesildi. Son tıklamanın indirme başlatıp başlatmadığı ve tamamlanma
sonucu doğrulanamadı; bu timeout doğal indirmenin başarısızlığı diye
yorumlanmaz. Dokümante edilmiş yeni sekme bağlama/AX/DOM denemeleri
kontrolü geri getirmedi; kullanıcıdan bağlantıyı yenilemesi istendi.
Tarayıcı profili, cookie deposu veya ham debugger/CDP ile erişim
zorlanmadı. Mevcut UYAP/JurisAI sekmeleri sonraki kontrol için korundu.

Chrome'un uzun indirmelerde yalnız etkin işlem boyunca API heartbeat
önerisi [resmî worker geçiş belgesinden](https://developer.chrome.com/docs/extensions/develop/migrate/to-service-workers)
teyit edildi; mevcut kod bu yöntemi zaten kullanıyor. Bu, Ek 41'de
kesintinin worker kaynaklı olmadığını kanıtlamaz ve yayın kabulü değildir.
**Ek 41 canlı sorunu açık; v2.26.28'in bunu çözdüğü iddia edilmez.**

## 11 Ekim 2026 — devir, canlı kabul ve Ek 41'in kapanması

UYAP işi bu tarihten itibaren ürün oturumunda yürütülüyor (kullanıcı kararı). Kod değişikliği: `api/uyap_sync.py`
`sync_status` doğrulama kaydını şimdiki evrak sayısıyla karşılaştırır (evrak silindikten sonra "eksiksiz" görünmez);
ortak test veritabanına 051 migration'ı uygulandı (Python testleri 0 hata, web 374/374).

Canlı koşu (v2.26.28, eklentili ayrı Chromium, kullanıcı bir kez giriş yaptı, geçici anahtar iş bitince iptal edildi,
profil silindi). **PC'deki karar toplayıcıları koşu boyunca duraklatıldı** (veri oturumu, 17:40:43).

| Adım | Sonuç |
| --- | --- |
| Liste | 21 dosya (2 ceza, 2 hukuk, 17 icra), liste eksiksiz |
| Yalnız denetle | 1382 evrak bulundu / 1381 kayıtlı / 1 eksik; 18 eksiksiz, 2 evraksız, 1 eksik (2024/124); dosya bilgileri 21/21 eksiksiz |
| Yalnız 2024/124 eksiğini aktar | 1 evrak aktarıldı (74,9 MB ZIP, ~80 sn, ilk denemede); 350/350, eksik 0 |
| Sunucu kontrolü | mükerrer evrak kimliği grubu 0; 2024/124 doğrulama kaydı 350/350 eksiksiz olarak yenilendi |

**Ek 41 bulgusu:** aynı ek 10 Ekim'de toplayıcılar çalışırken üç denemede 18,4 / 28,4 / 33,7 MB'ta kesilmişti; toplayıcılar
dururken ilk denemede tam indi. Tek karşılaştırmadır, kesin kanıt değildir; ama kesintinin eklentiden değil, aynı IP'den
adalet.gov.tr'ye giden toplu isteklerden kaynaklandığına güçlü işarettir (bkz. 6 Ekim'de aynı nedenle UYAP'ın hiç açılmaması).
Gerçek kullanıcıda bu yük olmaz; geliştirme makinesinde büyük UYAP aktarımından önce PC toplayıcıları duraklatılır.

İlk denetim denemesinde kayıt karşılaştırması 0 döndü: canlı pencereye API adresini `127.0.0.1` diye yazmıştım, eklentinin
izni `localhost:8766` içindir (ön denetim isteği 400). Ürün hatası değil, deneme düzeneği hatası; adres düzeltilip yinelendi.
