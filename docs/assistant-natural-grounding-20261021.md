# Asistanın doğal, kaynakla sınırlı cevap akışı

21 Ekim 2026. Eski tam-alıntı denetleyicisi kaldırılmadı; doğal yazım için ayrı
bir kanıt ve denetim hattı eklendi.

## Davranış

- Tamamı sosyal ifadelerden oluşan selamlaşma/teşekkür/yardım mesajları yerel,
  uygulamaya ait metinle yanıtlanır. Karma hukuki sorular bu kısa yola girmez.
- Hukuki soruda yalnız mevcut, doğrulanmış korpus ve yetkili kullanıcının seçili
  çalışma alanı aranır. Yeni doğal akışta sorgu sırasında web araması, portal
  indirmesi veya bekleyen arşivin canlı doğrulanıp cevaba eklenmesi yoktur.
- Model doğrudan, doğal Türkçe iddialar yazar. Her iddianın kanıtı, getirilen
  kaynakta gerçekten bulunan tam cümle/alan satırı olmalıdır.
- Kaynak kimliği/güveni, kanıt eşleşmesi, sayılar ve birimler, olumsuzluk,
  koşul/istisna ve olaya özgü kapsam kodla denetlenir. İkinci model çağrısı
  her iddianın anlam desteğini ve bütün cevabın önemli koşulları korumasını
  ayrıca değerlendirir. Belirsiz/bozuk/eksik onay kabul edilmez.
- Madde etiketi (`MADDE <gerçek madde no> -`) hukuki cümleyle karıştırılmaz:
  yazar etiketi atladıysa tam özgün kanıt birimi sunucu tarafından çözümlenir ve
  denetçiye o tam birim verilir. Koşul, istisna veya sürüm notu bu yolla atılamaz.
- Kaynak yetersizse açıkça söylenir; eksik olay bilgisi gerekiyorsa yeni hukuki
  varsayım içermeyen bir soru sorulabilir. Soru-only cevap kaynaklı hukuki
  sonuç diye işaretlenmez.
- Sentez reddedilirse taslak gösterilmez ve kullanıcının istemediği tam maddeye
  dönülmez. Sunucu kısa bir üretim/doğrulama başarısızlığı bildirir; bu durum
  bütün korpusta bilgi olmadığı anlamına gelmez. Eski, doğal-mod dışındaki
  alıntı hattı ve kayıt alanlarının aynen korunması ayrı kalır.
- Kişisel somut sonuç için eksik olay bilgisi önce nötr bir soruyla netleştirilir.
  Kaynak terimlerine göre sunulan sonlu uygulama soruları (sözleşme tarihi,
  tebliğ tarihi, mevcut tutar) aynen seçilmişse, hukuki iddia içermeyen bir girdi
  kontrolü olarak gösterilir; modelin ekleyebileceği metin bu kısa yola alınmaz.
  Tek bir hukuki iddia bile varsa veya soru serbest yazılmışsa bağımsız denetim
  zorunludur. Bilinen tarih/tutar tekrar bu seçeneklerle sorulmaz.
  Kaynakta gerçekten geçen sayısal eşikler sorulabilir; yeni oran veya süre
  eklenemez ve soru da bağımsız anlam denetiminden geçer. Resmî oran veya hukuk
  kuralı kullanıcıya geri sorularak cevap yükü kullanıcıya devredilmez.
- Olay bilgisi ile kaynak verisi eksikliği ayrılır: `source_gap:true` ikinci
  denetçi tarafından da onaylanırsa sunucunun sabit, yalnız getirilen kaynaklara
  ilişkin eksiklik bildirimi kullanılır; keyfî bir model açıklaması eklenmez.
  Böyle bir taslak desteklenmeyen iddialarla karışmışsa taslağın bütün metni
  ve sorusu atılır, yalnız kaynak-eksikliği durumu özgün girdilerle yeniden
  denetlenir. Reddedilen iddialar kısmen dahi kullanıcıya sızdırılmaz.
- Tam ve ardışık kanıt cümleleri aynı alıntıda çözümlenebilir; aradaki cümle,
  koşul veya kelime atılamaz. Geçerlilik tavanının eşdeğer olumsuz anlatımı
  yanlışlıkla eksik olgu koşulu sayılmaz; diğer koşullar ve anlam denetimi kalır.
- İlk taslakta mekanik bir kanıt/biçim/koşul hatası varsa en fazla bir düzeltme
  denemesi yapılır; bütün kontroller yeniden çalışır. Anlam denetçisinin reddi
  veya sağlayıcı hatası tekrarlı model çağrısına yol açmaz.

## Güvenlik ve uyumluluk

`answer_kind`: `legal` (eski kayıtlarda varsayılan), `conversation`,
`clarification`, `insufficient_sources`. Yanıt, ilerleme ve sohbet geçmişinde
taşınır. Sosyal cevap kaynak uyarısı üretmez; gerçek hatalı atıflar gizlenmez.
Selamlaşmada bile mevcut sohbetin sahiplik/kapsam kontrolü yapılır.

Özel dava/proje/seçili belge soruları hem yazıcı hem denetçide yerel kalır.
Kullanıcı belgesi barındıran bağlam için ikinci bir yerel yönlendirme kapısı
korunur. UYAP kayıtlarındaki kişi/bakiye alanları aynen-alıntı yolunda kalır.
Sosyal turlar hukuki takip sorularının konusunu geçmişten düşürmez.

Doğal cevapların tam kanıt paketi önbellekten yeniden denetlenene kadar bu
cevaplar önbelleğe alınmaz. Eski tam-alıntı önbelleği ve kullanıcı girdileriyle
Decimal hesap yapan açık aritmetik kısa yolu ayrı tutulur. Genel kural sorusu
konuya özel hesap şablonuna çevrilmez.

Reddedilen taslak, kaynak metni ve özel olay bilgisi günlüğe yazılmaz.
Sentez tanılaması yalnız `status` ve sabit `reason` kategorisi taşır.

## Ayarlar ve sınırların anlamı

`RAG_NATURAL_ANSWERS=true` varsayılandır; eski hattı seçmek için kapatılabilir.
`RAG_SYNTHESIS_CONTEXT_CHARS=24000` kaynak bağlamının teknik bütçesidir;
kullanıcıya aylık kota veya dört cümlelik cevap sınırı getirmez. Küçük yerel
modelin bağlam kapasitesi ayrıca dikkate alınır. Kesilmiş kaynak koşulu
kanıt sayılmaz. DeepSeek çıktı/token politikası değiştirilmemiştir.

Bu mekanizmalar risk azaltır; anlam denetimi model tabanlı olduğundan matematiksel
doğruluk veya sıfır hukuki hata garantisi değildir. Canlı kabul testi ve zorlayıcı
regresyon örnekleri geliştirmeye devam etmelidir. Korpusta olmayan güncel oran,
süre veya karar modelin ezberinden tamamlanmaz.

İlgili testler: `test_conversation_intent.py`, `test_assistant_routing.py`,
`test_synthesis.py`; ayrıca mevcut kaynak/atıf, gizlilik, kapsam, geçmiş ve
bulut sağlayıcı testleri. Veritabanı entegrasyon testleri yalnız ayrı `_test`
veritabanıyla, tarayıcı entegrasyonu açıkça etkinleştirildiğinde çalışır.

Son otomatik koşu: 2.005 Python testi geçti, 428 isteğe bağlı DB/tarayıcı testi
atlandı; 558 web testi geçti. Bu turda arayüz kodu değiştirilmedi. İlk tüm-suite
denemesi mevcut ortak pytest geçici dizininin Windows izinlerinden etkilendi;
yeni, bu koşuya özel bir geçici dizinle bütün testler tekrar çalıştırıldı.

21 Ekim akşamı kabul notu: kullanıcının birebir “kiraya ne kadar zam yaparım en
fazla” sorusu gerçek korpus/DeepSeek/pipeline ile art arda üç denemede kaynakla
denetlenmiş nötr netleştirme sorusuna dönüştü. Genel “TÜFE oranını aşabilir miyim?”
sorusu doğal ve atıflı açıklamaya dönüştü. Sentetik konut/tarih/tutar devamında
güncel oran kaynakta olmadığı için kaynak-eksikliği bildirimi bağımsız denetimden
geçti; kullanıcının tutar/tarih bilgisi kanun kanıtı yerine geçirilmedi.

Genel bir sohbetin sahiplik ve tam kapsam denetimi geçtikten sonra yalnız sohbet
kimliğinin bulunması güncel madde kısa yolunu kapatmaz. Tarih/konu/tam-madde
kontrolleri değişmedi; özel dava/proje/seçili belge kapsamı bu iyileştirmeye girmez.

Bu örnekler bütün sorularda aynı başarı oranı veya sıfır hata garantisi değildir.
Ret, üretim başarısızlığı ve gerçek kaynak verisi eksikliği ayrılmalı; özellikle
somut oran istenen sorularda kaynakta olmayan yüzde uydurulmamalıdır.
