# Resmî internet araştırması: açık kaynak izin listesi

Kullanıcı kararı: 27 Ekim 2026. Genel hukuk araştırması yerel korpus yanında
yalnız tek tek tanımlı resmî kamu kaynaklarına başvurabilir. Bu belge tüm
devlet sitelerinin envanteri veya tüm kaynaklara her zaman erişim garantisi değildir.

## İlk kayıt: 21 kurum/kaynak grubu

| Kaynak | Birincil adres | Kullanım |
|---|---|---|
| Mevzuat Bilgi Sistemi | https://www.mevzuat.gov.tr/ | Konsolide mevzuat |
| Resmî Gazete | https://resmigazete.gov.tr/ | Yayım, değişiklik, yürürlük |
| TBMM | https://www.tbmm.gov.tr/kanun-ve-karar-bilgi-sistemi | Kabul metni, gerekçe, yasama geçmişi |
| Yargıtay | https://karararama.yargitay.gov.tr/ | Kararlar |
| Danıştay | https://karararama.danistay.gov.tr/ | Kararlar |
| Anayasa Mahkemesi | https://kararlarbilgibankasi.anayasa.gov.tr/kbb/ | Bireysel başvuru; ayrıca norm kararları bankası |
| UYAP Emsal | https://emsal.uyap.gov.tr/ | Kamuya yayımlanan emsal kararlar |
| Adalet Bakanlığı | https://mevzuat.adalet.gov.tr/ | Mevzuat ve içtihat |
| Sayıştay | https://www.sayistay.gov.tr/ | Kurumun yayımladığı kararlar |
| Uyuşmazlık Mahkemesi | https://www.uyusmazlik.gov.tr/ | Görev uyuşmazlıklarına ilişkin kararlar |
| Kamu Denetçiliği Kurumu | https://www.ombudsman.gov.tr/ | Tavsiye/kurum kararları; mahkeme hükmü sayılmaz |
| KVKK | https://www.kvkk.gov.tr/ | Kurul kararları, düzenlemeler |
| Rekabet Kurumu | https://www.rekabet.gov.tr/ | Kurul kararları, düzenlemeler |
| Kamu İhale Kurumu | https://www.ihale.gov.tr/ | İhale mevzuatı ve kurul kararları; bağlantılı ekapv2.kik.gov.tr ayrıca tanımlı |
| TÜİK | https://veriportali.tuik.gov.tr/ | Dönemi belirtilmiş resmî istatistikler |
| TCMB | https://www.tcmb.gov.tr/ | Faiz, kur ve mali veriler; evds3.tcmb.gov.tr ayrıca tanımlı |
| Çalışma ve Sosyal Güvenlik Bakanlığı | https://www.csgb.gov.tr/ | Çalışma hayatı duyuruları ve resmî veriler |
| SGK | https://www.sgk.gov.tr/ | Sosyal güvenlik duyuruları ve rehberleri |
| Gelir İdaresi | https://www.gib.gov.tr/ | Vergi düzenlemeleri ve açıklamaları |
| Hazine ve Maliye Bakanlığı | https://www.hmb.gov.tr/ | Resmî mali tutar/duyurular |
| Ticaret Bakanlığı | https://www.ticaret.gov.tr/ | Ticaret/tüketici düzenlemeleri ve açıklamalar |

## Kod ve sınırlar

Katalog ve URL kontrolü: `api/ai/official_sources.py`.

- Yalnız açıkça listelenmiş HTTPS hostları. `*.gov.tr`, otomatik alt alan adı
  izni veya bakanlık sayfasındaki her dış bağlantıya güven yok.
- AYM norm bankası, TÜİK data/veriportali, ilgili karar arama hostları ayrı ayrı
  kayıtlıdır. TÜİK data adresinin veriportali adresine yönlendiği doğrulandı.
- Resmî sayfalardaki Google/YouTube/sosyal medya/CDN/başka kurum bağlantıları
  kendiliğinden izin kazanmaz. Yeni resmî host ayrıca incelenip kaydedilir.
- Vatandaş/avukat UYAP girişleri, e-Devlet ve kişisel oturum portalları genel
  internet araştırmasının kapsamında değildir. Parola/çerez veya özel dava,
  belge, kişi bilgisi dış aramaya gönderilmez.
- Her redirect adımı yeniden doğrulanır. URL kontrolü tek başına SSRF savunması
  değildir: ağ istemcisi DNS/public IP kontrolü, TLS, boyut/süre sınırı, içerik
  tipi ve yönlendirme denetimini ayrıca uygulamalıdır.
- Kurumun resmî olması sayfanın doğru döneme ait, bağlayıcı veya soruyla ilgili
  olduğunu kanıtlamaz. Haber, görüş, rehber, istatistik, mevzuat ve karar ayrı
  sınıflardır. TBMM kabul metni güncel konsolide kanun yerine kullanılamaz.
- Arama özeti kanıt değildir; tam resmî metin okunur, başlık/kimlik/tarih,
  yürürlük ve kaynak hash'i kaydedilir. Resmî olmayan siteler fallback değildir.
- CAPTCHA/hız sınırı aşılmaz; erişilemeyen site başarısız erişim olarak
  raporlanır. 'Tüm resmî siteler eksiksiz tarandı' gibi bir sonuç uydurulmaz.

27 Ekim kontrolünde Danıştay karar arama, AYM bankaları, UYAP Emsal, TÜİK,
KVKK, SGK, KİK ve ilgili bakanlık sayfalarının resmî içerikleri/bağlantıları
görüldü. Bazı adresler (Resmî Gazete www, MBS, TCMB, Uyuşmazlık) bu tarayıcı
aracında zaman aşımı; Rekabet 418, KDK 502 verdi. Bu erişim hataları kurumun
resmîliğini kaldırmaz, ama içerik okunmuş/doğrulanmış sayılmaz.

## Devredeki hat — 27 Ekim 2026

`OFFICIAL_WEB_RESEARCH_ENABLED=true` ile normal, özel kapsam içermeyen güncel
sohbet hattına bağlandı (`api/ai/official_research.py`, `pipeline.py`). Yerel
arama boşsa veya açıkça istenen madde eksikse erken "bulunamadı" dönüşünden
önce çalışır; çok parçalı doğal cevap planında da kaynak havuzunu tamamlar.
Özel belge/dava/proje ve tarihsel `as_of` sorgularında bu hat kapalıdır.

**Canlı bağlanan kurumlar MBS ve Yargıtay'dır.** Katalogdaki diğer 19 kurum
izinli olabilir ama bu kod tarafından aranmış sayılmaz. İlgili mevcut yerel
doğrulanmış kayıtlar normal korpus aramasında kullanılmaya devam eder.

- Dışarıya ham soru veya sohbet geçmişi değil, yalnız sayısal kanun/madde
  referansları ve sabit hukuk sözlüğünden terimler gönderilir. Bu sözlük bir
  hukuki cevap/kanıt tablosu değildir. Sözlük dışında kalan konular için web
  araştırması yapılmış gibi sonuç üretilmez.
- MBS: gözlenen resmî arama → resmî PDF → başlık/kanun numarası kontrolü →
  tekil madde çıkarımı → hash ve menşe kaydı → korpustan kaynak okuma.
  Mevcut farklı metin sohbet içinden değiştirilmez; ayrı sürüm incelemesi gerekir.
- Yargıtay: resmî arama → en fazla iki tam karar → metindeki E./K. ile arama
  künyesini karşılaştırma → korpusa kaydetme → normal kaynak okuyucudan okuma.
  Arama eşleşme sayısı incelenen karar sayısı değildir; `exhaustive=false` kalır.
- Kaydı tamamlanmamış sonuç veya arama özeti modele kanıt olarak verilmez.
  Kaynaklar yine mevcut cümle/iddia denetiminden geçer. Denetimsiz taslak yoktur.
- HTTPS/DNS/public-IP pinleme, TLS sertifika kontrolü, her yönlendirmede host
  denetimi ve boyut sınırları `official_transport.py` içindedir. POST yalnız
  gözlenmiş üç public arama yoluna açıktır; POST yönlendirmesi reddedilir.
- Portal çağrıları tek istemci olarak en az 4,5 saniye aralıkla yapılır; otomatik
  retry yoktur. Aynı kamu belgesi 15 dakika, karar araması 5 dakika, hatalı
  bağlantı 1 dakika önbelleklenir. Mevcut toplu çekici ayarları değiştirilmedi.
- Bir planda en fazla altı madde ve iki sabit hukuk terimi araştırılır; bu
  sınırlar ve ilk iki karar nedeniyle tam internet/korpus taraması iddiası yoktur.

Canlı, ücretli model kullanılmayan bağlantı kabulü: TBK 6098 PDF kimliği
doğrulandı (289.986 karakter). Yargıtay "kira" aramasında 124.038 eşleşme
bildirildi; iki doğrulanmış karar kalıcı kaynak zincirinden altı parça olarak
geri okundu. Bu, bütün hukuki cevapların doğru/eksiksiz olduğunun testi değildir.

Çevrimdışı testler ayrı raporlanır; gerçek modelle son kullanıcı cevabı bu
değişiklikte kredi harcanarak test edilmedi. API sağlık kontrolü 200 döndü.

