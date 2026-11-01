# DeepSeek Flash pilotu

## Güncel çıktı politikası — 21.10.2026

Kullanıcı kararı: kullanıcıya aylık kullanım kotası eklenmez; cevaplar küçük,
uygulamaya ait bir token tavanıyla kesilmez. Aşağıdaki ilk pilot kayıtlarındaki
4096 / 16384 / yardımcı 2048 token ayarları tarihî ölçümlerdir, güncel ayar değildir.

Genel sohbet ve araştırma için `CLOUD_AI_MAX_OUTPUT_TOKENS=0` ve
`DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS=0` kullanılır. **0, API'ye sıfır token
göndermez:** `max_tokens` alanı hiç gönderilmez; sağlayıcı model/mod varsayılanını
kullanır. Yardımcı çağrılarda da ayrı 2048 token / 45 saniye tavanı yoktur;
gereksiz uzun düşünmeyi önlemek için düşünme `none` kalır, ana çağrı değişmez.

Varsayılan kapasite `finish_reason=length` döndürürse aynı soru/kanıtlar,
sağlayıcının belgelenmiş azami çıktı kapasitesiyle (393216) **bir kez** yeniden
üretilir. Yarım JSON/cevap parçaları birleştirilmez. İki denemenin bildirilen
token kullanımı toplanır. Ağ/yetki/bakiye hataları bu nedenle tekrar edilmez;
ikinci kesilme yine hata olarak kalır. Sonsuz ücretli çağrı döngüsü yoktur.

Bu politika fiziksel olarak sınırsız model değildir: sağlayıcının bağlam/çıktı,
bakiye ve hizmet sınırları; bağlantı zaman aşımı; mevcut RAG kaynak kapsamı ve
doğrulama denetimi geçerlidir. Daha geniş çıktı uzun sorularda süreyi ve ücreti
artırabilir. Üst token kapasitesi her istekte tamamının üretileceği anlamına gelmez.
Özel dava/proje/seçili belge soruları hâlâ yerel modele gider; yerel Ollama'nın
bellek/bağlam ayarları bu değişiklikle kaldırılmaz. Kaynaksız hukuki sonuç üretilmez.

Yerel, git tarafından yok sayılan `.env` içinde yalnız bu iki token ayarı 0
yapıldı; anahtar değiştirilmedi. Çalışan API ayarları önbelleğe aldığından yeniden
başlatma gerekir. Doğrulama sahte HTTP yanıtlarıyla yapılır; ücretli API çağrısı,
kredi yükleme veya kullanıcı belgesi aktarımı yapılmaz.

Resmî sözleşme: https://api-docs.deepseek.com/api/create-chat-completion/

## İlk pilot kayıtları

20.10.2026: seçim `deepseek-flash`. Yerel modelin yerine bütün uygulamayı buluta
geçirmez. Yalnız kapsamı genel hukuk olan asistan sorularında isteğe bağlıdır.
Varsayılan olarak bulut kapalı kalır; bu hazırlık ücretli çağrı yapmaz.

## Aktivasyon öncesi

1. DeepSeek API hesabını ve bakiyeyi kullanıcı hazırlar. Sohbet hesabı veya
   ücretsiz web sohbeti API bakiyesi değildir. Anahtar sohbete/depo içine yazılmaz.
2. `DEEPSEEK_API_KEY` yalnız sunucunun secret ortamına veya git tarafından yok
   sayılan yerel `.env` dosyasına kullanıcı tarafından eklenir.
3. Veri işleme ve saklama şartları değerlendirilmeden özel belgeler buluta açılmaz.
   Genel sorulara serbestçe yazılan ad/adres/olay anlatımları da hassas olabilir.
   Mevcut regex maskeleme tam anonimleştirme veya KVKK uygunluğu garantisi değildir.
4. Kullanıcı, canlı test bütçesini ve genel/sentetik test verisini ayrıca onaylar.

Hazır olduğunda `.env.example` içindeki şu seçimler etkinleştirilir:

```dotenv
CLOUD_AI_PROVIDER=deepseek
CLOUD_AI_MODEL=deepseek-flash
CLOUD_AI_REASONING_EFFORT=low
CLOUD_AI_MAX_OUTPUT_TOKENS=0
CLOUD_AI_TIMEOUT_SECONDS=90
```

`DEEPSEEK_API_KEY` değeri bu dokümana eklenmez. `.env` değişikliği sonrasında API
süreci yeniden başlatılmalıdır; ayarlar süreçte önbelleğe alınır. Bu çalışma
ilk hazırlık aşamasında `.env` dosyasını değiştirmemiş ve API'yi yeniden
başlatmamıştır. Kullanıcı anahtar ekledikten sonraki aktivasyon aşağıda kayıtlıdır.

## Davranış ve bütçe

- Düşünme modu açık, başlangıç seviyesi `low`: API'nin örtük `high` varsayılanına
  bırakılmaz. `high` ve `max` isteğe bağlıdır; `none` düşünmeyi kapatır.
- `low` hız/maliyet başlangıç tercihidir; ücretsiz web arayüzündeki Derin Düşünme
  testiyle eşdeğer veya gerçek hukukta yeterli olduğu henüz ölçülmedi.
- Çağrı başına `max_tokens=4096`; düşünme de bu bütçeyi kullanır. Kesilmiş veya
  yalnız düşünme içeren cevap tamamlanmış yanıt olarak kabul edilmez.
- API'ye `tools` gönderilmez; sağlayıcının web araması kullanılmaz.
- JSON isteyen adımlarda JSON modu kullanılır; çıktı mevcut RAG/citation
  doğrulamasından geçmeden kullanıcıya sunulmaz.
- 402 bakiye, 401/403 yetki, 429 sınır ve bağlantı hatalarında yerel model devreye
  girer. İsteğin kalan çağrıları yerelde kalır; cevap yerel sağlayıcı/modeli bildirir
  ve DeepSeek önbelleğine konmaz. Kısmi cevaplar eski doğrulama kurallarına tabidir.
- Proje, dava, seçili belge kapsamındaki sorular ve kullanıcı belgesi içeren
  kaynaklar mevcut yerel yönlendirmeyi korur. Sohbet kapsamı değişikliği reddedilir.
- Maskeleme e-posta, kimlik numarası, telefon ve IBAN içindir; ad/adres ve bütün
  kişisel veri biçimlerini kapsamaz.
- Token tavanı AYLIK HARCAMA LİMİTİ DEĞİLDİR. Tek cevap birden çok model çağrısı
  yapabilir (soru yorumlama, cümle seçme, açıklama, doğrulama, özet). Mevcut sayaçlar
  bütün bu çağrıların toplam faturasını ölçmez. Kullanıcı bazlı bütçe kontrolü ve
  çağrıların toplam kullanım muhasebesi üretim yayını öncesinde ayrıca gerekir.
- Ortak üretim kilidi hâlâ vardır; bu pilot çok kullanıcılı yük testi değildir.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_cloud_provider.py tests/test_deepseek_cloud_pilot.py tests/test_deepseek_provider.py tests/test_ai_pipeline.py tests/test_citation_verification.py tests/test_conversation_scope.py
```

Bu testler MockTransport ve sahte kaynaklarla çalışır; gerçek DeepSeek ağına veya
ücretli API'ye istek yapmaz. Canlı kalite/hız/maliyet kabul testi yerine geçmez.

Resmî sözleşme: https://api-docs.deepseek.com/api/create-chat-completion/

Düşünme ayarları: https://api-docs.deepseek.com/guides/thinking_mode/

## Derin Araştırma: ayrı Pro profili

20.10.2026: `/api/office-ai/deep-research` içindeki üç araştırma ekseni için
`deepseek-v4-pro`, düşünme `max` profili hazırlandı. Bu bir kalite sonucu değil,
canlı kabul testinde değerlendirilecek güçlü model yapılandırmasıdır. Genel
asistanın Flash/low ayarı, risk analizi ve özel belge üretimi değiştirilmez.
Olay anlatımını konuya indirgeme yerelde kalır. Model kendi başına internette
arama yapmaz; mevcut mevzuat/içtihat/usul planı ve doğrulanmış korpus kullanılır.

Genel bulutu açmadan yalnız araştırmayı açmak mümkündür. Kullanıcı anahtarı ve
canlı test bütçesini hazırladığında sunucu ortamında şu ayarlar etkinleştirilir:

```dotenv
DEEP_RESEARCH_CLOUD_ENABLED=true
DEEP_RESEARCH_AI_MODEL=deepseek-v4-pro
DEEP_RESEARCH_AI_REASONING_EFFORT=max
DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS=0
DEEP_RESEARCH_AI_TIMEOUT_SECONDS=180
```

Aynı `DEEPSEEK_API_KEY` gizlice okunur; anahtar genel sohbet bulut sağlayıcısından
bağımsızdır. Profil HTTP istek gövdesinden seçilemez. Etkinleştirme/anahtar yoksa
araştırma yerelde yürür; sessizce Flash'a dönmez. Özel kapsamlar ve kullanıcı
belgesi içeren kaynaklar Pro profilinde de buluta gönderilmez. API hatasında
yerel dönüş korunur; her adımın `provider` ve `model` alanları gerçek modeli
kaydeder (API yanıtında ve kaydedilen raporun kaynak metadatasında). İç düşünme
metni kullanıcıya/rapora taşınmaz. Eski raporlarda model alanı olmayabilir.

16384 token tavanı düşünme + cevabı kapsar; `max` düşünme ile kesilme hâlâ mümkün.
Token sınırında kesilen çıktı tamamlanmış cevap sayılmaz. Araştırma üç eksendir
ve her eksen birden fazla model çağrısı yapabilir: **16384 tüm araştırmanın ya da
aylık harcamanın tavanı değildir.** Zaman aşımı da çağrı başınadır. İlk hazırlıkta
anahtar olmadığı için canlı test yapılmadı; sonraki test sonuçları aşağıdadır.

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_deep_research_model.py tests/test_deep_research.py tests/test_deepseek_cloud_pilot.py
```

Resmî model listesi: https://api-docs.deepseek.com/quick_start/pricing/

### İlk canlı kontrol — 20.10.2026

Kullanıcının yerel secret ortamına anahtar eklemesinden sonra resmî API'den
bakiye ve model listesi okundu: kullanılabilir hediye bakiye 6 CNY, Flash ve Pro
erişilebilir. Anahtar çıktıya/rapora/depo dosyasına alınmadı. Kart veya yükleme yok.

Salt okunur gerçek korpustan TBK 344 getirilip Pro/max ile tek kanıt seçimi
çağrısı yapıldı: 3,29 sn model süresi, 1096 giriş / 194 çıkış tokenı,
`finish_reason=stop`, 1 atıf, `grounded=true`, 0 geçersiz işaret / desteklenmeyen
iddia. Kullanıcı belgesi veya geçmişi gönderilmedi; cevap veritabanına yazılmadı.
Bu dar kapsamlı bağlantı/kanıt seçimi testidir, bütün araştırma akışının hukukî
kalitesi veya çok kullanıcılı yük testi değildir.

İlk normal madde sorgusu 3 saniyelik süre sınırında `QueryCanceled` verdi;
aynı politika ile salt okunur tanı sorgusu 0,15 sn, normal sorgunun tekrarı 0,239 sn
sürdü. Model hatası değildi; üretim sorgu bütçeleri veya kaynak filtreleri değiştirilmedi.

Yerel, git tarafından yok sayılan `.env` içinde yalnız araştırma Pro/max profili
açıldı. Çalışan API önbellekli ayar kullandığından yeniden başlatma gerekir;
aktif aktarım/araştırmayı kesmemek için kullanıcı onayı istenir. Anahtar veya
bakiyenin yetmediği durumda arayüzde her adımın gerçek modeli gösterilir;
eski raporlara model adı yakıştırılmaz.

### Canlı cevap hattında bulunan sorun ve düzeltme

İlk tam cevap hattı denemesinde ana kanıt seçimi tamamlandı, ancak kısa yardımcı
çağrı Pro/max ile 16.384 tokena ulaşıp 101,95 sn sonunda kesildi; yerel dönüşle
toplam 124,84 sn sürdü. `low` düşünme + 2048 token da sınırda kesildi (12,89 sn;
toplam 27,26 sn). Bu nedenle yalnız araştırmanın **yardımcı** işleri için düşünme
kapatıldı (`none`); aynı Pro modeli, en fazla 2048 çıktı tokenı ve 45 sn çağrı
zaman aşımı kullanılıyor. Ana kanıt seçimi hâlâ Pro/max, 16384 token / 180 sn.
Genel asistanın modeli/ayarları değişmedi. Dava/belge kapsamları yerelde kalır.

Yardımcı bütçe soru yorumlama, açıklama ve özet/kontrol çağrılarında uygulanır;
ana sağlayıcının ayarları yerinde değiştirilmez. Hata hâlinde mevcut yerel dönüş
ve gerçek model raporlaması korunur. Önbellek anahtarı yardımcı bütçe sürümünü de
içerir. Ana/yardımcı çağrıların farklı token bütçeleri aylık bütçe sınırı değildir.

Düzeltme sonrası gerçek cevap hattı (TBK 344, kayıt/geçmiş olmadan):

- Toplam 17,10 sn, gerçek yanıt modeli `deepseek-v4-pro`; yerel dönüş yok.
- Ana çağrı max: 6,50 sn, 1096 giriş / 436 çıkış tokenı.
- Yardımcı çağrılar none: 3,73 sn (1050/361 token), 1,69 sn (1359/11 token).
- 1 kaynaklı atıf, `grounded=true`, 0 geçersiz işaret, 4 özet maddesi.
- 0 özel belge, sohbet kaydı oluşturulmadı. Toplam 3505 giriş / 808 çıkış tokenı.

Normal akışta ilgili bekleyen mevzuat adaylarını yükleyen ayrı sorguda
`QueryCanceled` uyarısı gözlendi. Bu kaynak eksiksizliği/arama gecikmesi ayrı bir
inceleme konusudur; resmî kaynak filtresi gevşetilmedi. Bu denemeler tek bir
örnek soruyu kapsar; üç eksenli araştırmanın kapsamı, tüm hukuk konuları veya
çok kullanıcılı yük için kabul testi sayılmaz.

Kullanıcı aktif işlem olmadığını belirterek API yeniden başlatmasına onay verdi;
testten geçen düzeltme yerel API'ye yüklendi. Arayüzde her adımın gerçek modeli
gösterilir. Son bakiye sorgusunda API 5,69 CNY gösterdi; görüntülenen iki haneli
bakiye tam token faturası değildir. Kart/yükleme yapılmadı, anahtar git dışında.

## Genel sohbet aktivasyonu — 21.10.2026

Kullanıcının "bağla o zaman deepseki" isteğiyle yerel `.env` içinde genel
sohbet için Flash/low, 4096 token ve 90 sn çağrı zaman aşımı etkinleştirildi.
Araştırma Pro/max olarak kaldı. Dava/proje/seçili belge kapsamları ve özel
belge içeren kaynak listeleri hâlâ yerel modele yönlenir. Anahtar kopyalanmadı
ve hiçbir çıktıya yazılmadı. Ödeme/yükleme yapılmadı.

Kısa yardımcı çağrıların none/2048 token/45 sn bütçesi genel Flash sohbetine
de uygulandı; ana Flash/low ayarı yerinde değiştirilmez. Diğer sağlayıcıların
genel sohbet davranışı değişmedi. Önbellek yardımcı çağrı politikasını içerir.

Eski API'nin hâlâ Qwen döndürdüğü salt test ile saptandı; yalnız doğrulanan
8766 API süreçleri yeniden başlatıldı. Ardından normal sohbetin gerçek
`POST /api/ai/answer/progress` akışı test edildi: HTTP 200,
`application/x-ndjson`, `done` olayı, sağlayıcı `deepseek`, model
`deepseek-flash`, `grounded=true`, 1 atıf / 0 geçersiz işaret, toplam 8,35 sn.
Önbellek kullanılmadı, özel belge gönderilmedi, sohbet kaydı oluşturulmadı.
Bu test önceki tarayıcıdaki bağlantı kesintisinin kök nedenini kanıtlamaz;
genel sohbetin yeni sağlayıcıyla tamamlandığını doğrular.
