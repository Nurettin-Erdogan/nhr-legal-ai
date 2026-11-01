# nhr-legal-ai

NHR Yazılım'ın avukatlara sunulmak üzere geliştirdiği ticari Türk hukuku AI
platformu. Kişisel bir araç değil. Apilex referanslardan biridir, birebir
kopyalanmaz.

## Ürünün iki temel parçası

Bunlar alternatif değil, aynı platformun birlikte geliştirilen parçalarıdır.

1. **Merkezi Türk hukuk bilgi tabanı** — mevzuat, Yargıtay, Danıştay, AYM ve
   ileride diğer karar kaynakları.
2. **Kullanıcıya özel çalışma alanı** — müvekkil, proje/dava, yüklenen
   belgeler, sohbetler ve kaydedilen kaynaklar.

## Öncelik sırası

1. Mevcut RAG/citation çekirdeğini sağlamlaştır
2. Mevzuat ingestion
3. Yargıtay korpusunu büyüt, metadata kalitesini iyileştir
4. Belge yükleme, parsing, document chunking, proje bazlı RAG
5. Sohbet geçmişi
6. Müvekkil / proje / belge / sohbet ilişkileri
7. Belge üretme ve analiz akışları
8. Çoklu sağlayıcı yönlendirmesi

## Değişmez kurallar

**Kaynaksız hukuki iddia üretilmez.** Doğrulanabilir kaynak olmadan karar,
mevzuat maddesi veya hukuki sonuç uydurulamaz. Kaynak yetersizse bu açıkça
söylenir. Bu kural model promptunda kalmaz; üretilen cevabın gerçekten
getirilen kaynaklara dayandığı kod tarafında doğrulanır.

**Normal sohbette genel bilgi istisnası (kullanıcı kararı 2026-10-26).** Önce kaynaklar aranır ve kaynaklı doğal cevap tercih edilir.
Yalnız tek başına anlaşılır basit kavram tanımlarında, kaynakla cevap üretilemezse modelin genel bilgisiyle kısa açıklama verilebilir
(`api/ai/general_information.py`); bu cevap `general_information`, `grounded=false`, atıfsızdır ve arayüzde "Genel bilgi" olarak
işaretlenir. Model bilgisi hiçbir zaman doğrulanmış kaynak veya sonraki hukuki iddiaların kanıtı sayılmaz. Süre, güncel oran/tutar,
hesaplama, kişisel hak/sonuç ve kanun/karar atfı bu istisnaya girmez; kod denetimi devam eder. Özel belge/dava/proje ve derin araştırma
bu yolu kullanmaz. Normal sohbette denetlenmemiş taslak yayınlanmaz; denetimden geçmiş son cevap bir kez gösterilir.

**Genel sohbetin cevap düzeni (kullanıcı kararı 2026-10-25).** Model, soru için bulunmuş doğrulanmış kanun ve karar kaynaklarını
okuyup yalnız onlara dayanarak akıcı paragraflar yazar; her cümleyi dayandığı kaynak cümlelerine bağlar
([api/ai/free_answer.py](api/ai/free_answer.py)). Kod her cümleyi denetler (alıntı gerçekten o kaynakta mı, sayı/birim, eklenen
alt/üst sınır, mutlaklık, ödeme yönü) ve bağımsız bir denetçi model kaynağa karşı sınar; kaynaktan kopan cümle cevaptan sessizce
çıkarılır, bu kaynaklı cevap yolunda gösterilen her cümle kanıtlıdır; metinde [K1] gibi işaret bulunmaz (kullanıcı kararı 2026-10-25), kullanılan kaynaklar
cevabın altındaki kaynak listesinde durur. İlk (doğrudan cevap) cümle kanıtlanamazsa yalnız kanıtlı cümlelerden yeniden kurulur
ve aynı denetimden geçer. Yeterli cümle kalmazsa cevap
verilmez, "doğrulayamadım" denir. Bu düzen yalnız bulut modeline gidebilen genel sorularda geçerlidir; kullanıcının kendi belgesi,
davası ya da projesi kapsamındaki sorular buluta gitmez ve kaynakla-sınırlı sentez yolunu (api/ai/synthesis.py) kullanır.

**Doğrulanmamış kaynak "resmî" diye sunulmaz.** Korpusta üçüncü taraf derlemeden
gelen kayıtlar da var (`ingestion_method='bulk_seed'`, `ingest_status='pending'`; 2026-09-20'de ~10,2 milyondu,
2026-10-25 itibarıyla ~124 bin kaldı — kararların geri kalanı, ~11,1 milyon, resmî portallardan doğrulanmış `ready`). Kullanıcı kararı
2026-10-18: **uygulamada yalnız doğrulanmış kayıtlar aranır, gösterilir ve atıf
yapılır.** Doğrulanmamış toplu kayıtlar veritabanında durur ama arama, asistan,
araştırma ve kaynak okuyucu onları döndürmez (migration 058, `api/legal.py`
`_VERIFIED_SOURCE_FILTER`); doğrulanıp `ready` olunca kendiliğinden görünür.
Her görünen kaynak doğrulanmış olduğundan arayüzdeki "Resmî metin ✓ /
doğrulanmamış" ayrımı kaldırıldı: karar künyesiyle ("Yargıtay kararı · E./K. no")
ve resmî portalda açan "Resmî sitede aç" bağlantısıyla gösterilir; yalnız
kullanıcının kendi belgesi "kullanıcı belgesi" diye ayrılır. Resmî olmayan bir kayıt
(ör. eski bir sohbette kalmış atıf) hiçbir yerde "doğrulandı", "resmî" ya da ✓ ile
gösterilmez.
Bir kayıt ancak resmî portaldan çekilip metni eşleştiğinde `ready` olur
([docs/ingestion-bulk-mrfg.md](docs/ingestion-bulk-mrfg.md)). Doğrulanmamış kaydı
yeniden uygulamaya açmak kullanıcı kararı olmadan yapılmaz.

**Resmî internet araştırması (kullanıcı kararı 2026-10-27).** Genel hukuk sorularında yerel korpusa ek olarak yalnız açık izin listesindeki resmî kamu kaynaklarından araştırma yapılabilir. Katalog ve URL politikası `api/ai/official_sources.py`, kapsam ve güvenlik şartları `docs/official-web-source-policy.md` içindedir. Tüm `.gov.tr` adresleri veya alt alan adları otomatik izinli değildir. Arama özeti kanıt sayılmaz; tam resmî metin, kimlik, tarih ve yürürlük ayrıca doğrulanır. Resmî olmayan siteye fallback, CAPTCHA/hız sınırı aşma ve özel dava/belge/kişi bilgisini dış aramaya gönderme yoktur. Bu karar kaynak-destek ve özel kapsam/bulut kurallarını kaldırmaz. `OFFICIAL_WEB_RESEARCH_ENABLED` ile normal genel sohbette MBS ve Yargıtay adaptörleri bağlandı; diğer katalog kurumları henüz canlı araştırılmış sayılmaz. Ham sorular yerine yalnız sayısal mevzuat referansları ve sabit hukuk terimleri dışarı gider; özel kapsam ve tarihsel sorular web hattına girmez. Kaynak önce kalıcı korpusa alınır, sonra mevcut cevap/atıf denetimiyle kullanılır; farklı mevcut metin sohbetten otomatik değiştirilmez.

**AI katmanı sağlayıcıdan bağımsız kalır.** Yerel üretim Ollama üzerinden gider
(şu an `qwen3.5:4b`); üretim ve embedding çağrıları arayüz arkasında tutulur. Model
sıfırdan eğitilmez. İsteğe bağlı bulut modeli (`CLOUD_AI_PROVIDER`, varsayılan
kapalı) yalnız genel hukuk sorularında kullanılır: dava, proje ya da seçili belge
kapsamındaki soru ve kullanıcı belgesi içeren kaynak listesi hiçbir zaman buluta
gitmez ([api/ai/cloud_provider.py](api/ai/cloud_provider.py)); cevap yine aynı kod
denetiminden geçer. Mevzuat anlam araması ayrıca yerel `bge-m3` gömme modelini kullanır
(migration 061, `scripts/embed_legislation_m3.py`); sunucuda Ollama'ya bu model de kurulmalıdır.

**Güvenlik ve KVKK sonradan eklenmez.** Kullanıcı izolasyonu, RLS, denetim
kaydı ve secret yönetimi mimarinin parçasıdır. Yeni bir tablo veya uç nokta
eklenirken erişim kontrolü aynı commit'te düşünülür. Uygulama veritabanına
`nhr_runtime` rolüyle bağlanır; `nhr_app` yalnızca migration, korpus aktarımı
ve kimlik doğrulama öncesi sorgular içindir. Kullanıcıya ait tablolara satır
eklerken kimliği uygulamada üret, `RETURNING id` kullanma — gerekçesi
[docs/database-setup.md](docs/database-setup.md) içinde.

**Uygulamaya yalnız erişim listesindekiler girer.** Kullanıcı kararı 2026-10-24: "bu
uygulamaya sadece benim mailini eklediğim kişiler girmesi lazım". Erişim modu `allowlist`
(migration 062, Yönetim → Erişim); listede olmayan hesap kayıt olamaz, şifreyle ya da Google ile
giremez, açık oturumu her istekte reddedilir, UYAP eklentisi anahtarı da kabul edilmez
([api/access.py](api/access.py)). Yöneticiler her zaman girer. Yeni bir giriş yolu eklenirse
aynı denetimden geçirilir.

**`main` dalına doğrudan push veya merge yapılmaz.** Geliştirme
`feature/legal-ai` üzerinde sürer.

## Teknik yerleşim

### Tek bulut sağlayıcı kararı — 2026-11-01

Kullanıcı, özel belge/dava/UYAP içeriklerinin de AWS Bedrock'a gönderilmesini
açıkça onayladı. `AI_PROVIDER=bedrock` seçildiğinde bütün metin üretimi (normal
sohbet, özel kapsam, büro özeti/taslak, denetim ve araştırma) aynı Bedrock
modelini kullanır; yerel üretim/fallback yoktur. Bu açık mod, yukarıdaki eski
"özel kapsam yalnız yerel" sağlayıcı kuralının yerine geçer. RLS, erişim
kontrolü, kaynak denetimi, özel verilerin dış web aramasına ve genel cevap
önbelleğine gönderilmemesi kuralları aynen korunur. Diğer sağlayıcı
ayarlarında eski özel-kapsam davranışı devam eder.

Embedding metin üretiminden ayrıdır. Mevcut nomic/bge-m3 vektörleri farklı
bir bulut modelinin vektörleriyle karşılaştırılmaz; embedding geçişi ayrı
uyumluluk/veri göçü gerektirir. Bu geçiş yapılmadan tüm yerel model
bağımlılıkları kaldırılmış sayılmaz.

| Dizin | Sorumluluk |
| --- | --- |
| `database/` | V2 şeması, RLS politikaları, bütünlük tetikleyicileri, migrationlar |
| `ingestion/` | Hukuk korpusunu toplama, ayrıştırma, parçalama ve aktarma |
| `api/` | FastAPI: hukuk arama, RAG, kimlik doğrulama, projeler |
| `web/` | Next.js arayüzü |

Veritabanı PostgreSQL 16 + pgvector, Docker ile `localhost:5433`. Kurulum ve
migration adımları için [docs/database-setup.md](docs/database-setup.md),
korpus aktarımı için [docs/ingestion-yargitay.md](docs/ingestion-yargitay.md)
ve [docs/ingestion-mevzuat.md](docs/ingestion-mevzuat.md).

Testler ağ ve veritabanı olmadan çalışır; veritabanı testleri
`NHR_TEST_DATABASE_URL` tanımlıysa devreye girer ve yazdıklarını geri alır.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
