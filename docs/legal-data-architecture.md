# NHR Legal Data Layer

Bu doküman merkezi Türk hukuk korpusunun kaynak, kimlik, doğrulama,
versiyonlama ve denetim kurallarını tanımlar. Uygulama arayüzünden bağımsızdır;
`ingestion/`, `worker/`, `database/` ve RAG katmanı için ortak sözleşmedir.

## Temel ilke: transport ile hukuki kaynak aynı şey değildir

**Veriyi teknik olarak aldığımız endpoint** ile **hukuken referans verdiğimiz
resmî kaynak** aynı olmak zorunda değildir.

Örneğin bir mevzuat maddesi Bedesten JSON uçlarından hızlı biçimde taşınabilir.
Bu, Bedesten yanıtının tek başına mevzuatın yayımlanma ve yürürlük geçmişi için
nihai hukuki kanıt olduğu anlamına gelmez. Kullanıcıya verilen atıf kanun,
madde ve varsa Resmî Gazete künyesine dayanır; transport adresi ayrıca denetim
metadata'sı olarak tutulur.

| Adapter | Durum | Transport | Hukuki/canonical otorite |
| --- | --- | --- | --- |
| Yargıtay | ACTIVE | `karararama.yargitay.gov.tr` JSON/HTTP | Yargıtay Karar Arama / Yargıtay |
| Mevzuat | ACTIVE | `bedesten.adalet.gov.tr/mevzuat` JSON/HTTP | Mevzuat Bilgi Sistemi; Resmî Gazete teyidi ayrıca gerekir |
| Danıştay | ACTIVE | `karararama.danistay.gov.tr` JSON/HTTP | Danıştay Karar Arama / Danıştay |
| AYM | ACTIVE | Public arama JSON'u + public karar-dosyaları/UDF attachment | Anayasa Mahkemesi Kararlar Bilgi Bankası |
| Resmî Gazete | ACTIVE / VERIFICATION | `/Home/Filter` JSON + resmî arşiv HTML | Resmî Gazete |
| KDK | ACTIVE | `kararlar.ombudsman.gov.tr` public JSON + resmî PDF | Kamu Denetçiliği Kurumu |

PLANNED adapter'lar veri üretmez. Resmî portal sözleşmesi ve kullanım koşulları
doğrulanmadan tahminî selector, endpoint veya sahte kayıt eklenmez.

## Veri akışı

```text
resmî portal / transport
  -> source adapter
  -> ham snapshot (data/, Git dışında)
  -> normalize
  -> validation
  -> dedup identity + content hash
  -> created / unchanged / updated / new_version / quarantine
  -> PostgreSQL legal_sources + tür detayı + legal_chunks
  -> ayrı embedding backfill
  -> tarih ve kaynak filtreli RAG + citation
```

Korpus yazımı `nhr_app`/`DATABASE_ADMIN_URL` ile yapılır. FastAPI normal
çalışmada RLS uygulanan `nhr_runtime` rolünü kullanır. Embedding başarısızlığı
kaynak kaydını geri almaz; embedding ayrı ve tekrar çalıştırılabilir bir
zenginleştirmedir.

## Ortak adapter sözleşmesi

`worker/adapters/base.py` içindeki `SourceAdapter` şu davranışları zorunlu kılar:

- `health_check`: portalın erişim ve yanıt sözleşmesi durumu;
- `validate`: kaynağa özgü kritik alan kontrolü;
- `dedup_identity`: aynı hukuki belgenin tekrarını tanıyan kimlik;
- `version_identity`: aynı kimliğin içerik/sürüm ayrımı;
- `provenance`: kaynak ve çekim zinciri;
- `sync`: checkpoint ile devam edebilen toplama işlemi.

`YargitaySourceAdapter`, `DanistaySourceAdapter`, `MevzuatSourceAdapter`,
`KdkSourceAdapter` ve `AymSourceAdapter` aktiftir. Resmî Gazete bağımsız
korpus adapter'ı değil, mevzuat doğrulama katmanıdır.

AYM için `POST /api/core/public/search` ile yapılandırılmış künye,
`GET /api/core/public/kararlar/{id}/dosyalar` ile yayımlanmış dosya listesi ve
`GET /api/core/public/files/download-attachment/{folder}/{filename}` ile UDF
karar dosyası alınır. UDF içindeki `content.xml` güvenli boyut ve XML
kontrollerinden sonra ayrıştırılır; başvuru/esas numarası ve karar tarihi
arama künyesiyle metinde eşleşmezse kayıt reddedilip karantinaya alınır,
sonraki karara geçilir. Güvenlik doğrulaması isteyen PDF üretim ucu
kullanılmaz ve doğrulama başlığı taklit edilmez.

## Provenance standardı

Her `legal_sources` satırında aşağıdaki çekirdek alanlar korunur:

| Alan | Anlam |
| --- | --- |
| `source_type` | `court_decision`, `legislation` veya desteklenen diğer tür |
| `authority` | Belgeyi yayımlayan/yargısal otorite |
| `canonical_source_name` | Kullanıcı atfında esas alınan resmî kaynak adı |
| `official_source_url` | Resmî belge veya resmî portal adresi |
| `external_id` | Resmî belge kimliğinden türeyen dedup anahtarı |
| `ingestion_method` | Örn. `yargitay_public_json_http` |
| `fetched_at` | Payload'ın alındığı an |
| `published_at` | Biliniyorsa yayımlanma tarihi |
| `effective_from`, `effective_to` | Yalnız doğrulanmış yürürlük aralığı |
| `last_verified_at` | Kaynağın en son başarıyla doğrulandığı an |
| `content_hash` | Normalize metnin SHA-256 özeti |
| `source_version`, `revision` | Sürüm kimliği ve sıra numarası |
| `is_current`, `superseded_by_id` | Güncel satır ve onu değiştiren satır |
| `metadata` | Portal kimlikleri ve kaynağa özgü ek alanlar |

`legal_source_revisions` değişim anındaki metin, hash, metadata ve provenance
görüntüsünü tutar. Böylece güncelleme sebebi ve önceki içerik incelenebilir.

`official_source_url` mümkün olduğunda belgeye kalıcı bağlantıdır. Portal yalnız
bir sorgu/getirme adresi veriyorsa bu gerçek açıkça metadata'da korunur; kalıcı
URL varmış gibi üretilmez.

## Yargıtay akışı ve veri kalitesi

Transport sırası:

1. `GET /` ile oturum;
2. `POST /detayliArama` ile arama bağlamı;
3. `POST /aramadetaylist` ile yapılandırılmış liste;
4. `GET /getDokuman?id=...` ile karar metni.

Portal `document_id` değeri `yargitay:<id>` biçimindeki `external_id` için
birincil kaynaktır. Daire, esas numarası, karar numarası ve karar tarihi liste
JSON'undan alınır. Karar metninden künye ayrıştırma yalnız eski/düz metin
arşivleri için fallback'tir; yapılandırılmış alanın üzerine tahmin yazılmaz.

Validation en az resmî kimlik, mahkeme, esas no, karar no, karar tarihi ve karar
metnini ister. Eksik kayıt `legal_source_quarantine` tablosuna sebebi ve güvenli
ham payload özetiyle alınır; RAG korpusuna sessizce kabul edilmez.

Aynı `external_id` ve aynı hash `unchanged` sonucudur; chunk ve citation
kimliklerine dokunulmaz. Hash değişirse revision artar. Mevcut kaynağın chunk'ına
atıf varsa eski satır korunur, `is_current=false` yapılır ve yeni satır
`superseded_by_id` zinciriyle eklenir. Güncel doğal künye
`court_name + chamber + docket_no + decision_no` için veritabanında ayrıca tekildir.

Yargıtay aylık tarih pencereleriyle taranır. `source_coverage_windows` tarih
aralığı, daire, portalın bildirdiği sayı, görülen, saklanan, duplicate, başarısız
ve tamamlanma bilgisini tutar. `source_sync_checkpoints` son başarılı sync,
sayfa/pencere cursor'u, hata sayısı ve health durumunu saklar.

## Danıştay akışı

Danıştay adapter'ı resmî arayüzün oturumlu akışını kullanır:

1. `GET /` ile oturum;
2. `POST /detayliArama` ile tarih/daire arama bağlamı;
3. `POST /aramadetaylist` ile yapılandırılmış künye;
4. `GET /getDokuman?id=...` ile tam karar HTML'i.

`daireKurul`, `esasNo`, `kararNo` ve `kararTarihi` liste JSON'undan; karar
metni sayfadaki `hiddencontent` alanından alınır. Kimlik
`danistay:<document_id>` biçimindedir. CAPTCHA istenirse bypass uygulanmaz,
run `captcha_required` durumunda durur. Detaylı arama ucu serbest kelime
filtresi sunmadığından bu adapter şimdilik tarih ve daire pencereleriyle
çalışır.

## Mevzuat kimliği ve hukuki versiyonlama

Bir mevzuat maddesinin kalıcı kimliği ile metin sürümü ayrıdır:

```text
identity: (legislation_type, law_no, article_no)
version:  (legislation_identity_id, version_identity)
```

`legislation_identities` örneğin `law / 4857 / 25` maddesini temsil eder.
Her değişen metin ayrı `legal_sources` ve `legislation_details` satırı olarak
saklanır. `version_identity`, bilinen sürüm tarihi ve içerik hash'inden üretilir;
aynı identity/version çifti ikinci kez oluşturulamaz.

Aynı hash tekrar geldiğinde sonuç `unchanged` olur. Hash değiştiğinde eski metin
overwrite edilmez: eski satır tarihsel kalır, yeni revision/current satır açılır,
chunk'lar yeni kaynağa yazılır ve eski citation hedefleri korunur. Yalnızca bir
`legislation_type + law_no + article_no` satırı güncel olabilir.

Yeni sürümün doğrulanmış `effective_from` tarihi varsa eski açık aralığın
`effective_to` değeri yeni başlangıçtan bir gün önce kapanır. Yeni başlangıç
bilinmiyorsa sistem bugünün tarihini veya çekim tarihini yürürlük tarihi olarak
uydurmaz; eski aralık da tahminen kapatılmaz.

`official_gazette_date`, `official_gazette_no`, `amendment_source`,
`version_date`, `effective_from` ve `effective_to` birbirinden ayrı olgulardır.
Bir dokümanın portaldaki güncellenme tarihi otomatik olarak yürürlük tarihi
sayılmaz.

## Resmî Gazete doğrulaması

Bedesten hızlı transport kaynağıdır. Resmî Gazete çapraz doğrulaması
mevzuat sync'i içinde aktiftir. Doğrulayıcı:

- resmî `/Home/Filter` aramasında gazete sayısı ve mevzuat numarasını eşler;
- dönen URL'nin yalnız `resmigazete.gov.tr` alanında olmasını kabul eder;
- arşiv HTML'inde gazete sayısını ve mevzuat numarasını ikinci kez denetler;
- Bedesten'de tarih boşsa resmî arama sonucundaki tarihi doldurur;
- sonucu, arşiv URL'sini ve doğrulama zamanını metadata/provenance'ta saklar.

Bu katman bağımsız bir Resmî Gazete korpusu oluşturmaz ve yayın tarihini
otomatik olarak maddenin yürürlük tarihi saymaz. Sonraki adım, değişiklik
belgelerini madde sürümlerine kanıt bağlantısıyla eşlemektir.

## Change detection ve sync durumları

Normalize metin hash'i karşılaştırılır:

| Durum | Anlam | İşlem |
| --- | --- | --- |
| `created` | Yeni resmî/dedup kimliği | Yeni kaynak ve chunk |
| `unchanged` | Kimlik ve hash aynı | Verification zamanı güncellenir; chunk korunur |
| `updated` | Karar içeriği değişti | Revision/audit; atıf güvenliği gözetilir |
| `new_version` | Mevzuat metni değişti | Eski sürüm korunur, yeni current sürüm eklenir |
| `duplicate` | Tur içinde/kimlikte tekrar | Sayaç; yeni satır yok |
| `quarantined` | Kritik metadata eksik | Korpusa yazılmaz, inceleme kuyruğu |
| `failed` | Transport/parse/depolama hatası | Hata ve checkpoint kaydı |

`source_sync_runs` her turun filtrelerini, başlangıç/bitişini, sayaçları,
checkpoint öncesi/sonrasını ve hatayı tutar. Bir kaynak için PostgreSQL advisory
lock aynı anda iki sync'i engeller. Kesinti sonrası yalnız son güvenli cursor'dan
devam edilir.

Bir kaydın portalda artık görünmemesi tek başına hukuki olarak yürürlükten
kalktığı veya silindiği anlamına gelmez. “Kaldırılmış/erişilemeyen” durumu ayrı
gözlem olarak ele alınmalı; doğrulama olmadan `deleted_at` veya `effective_to`
atanmamalıdır.

## Ham snapshot ve audit

Normalize işleminden önce/yanında yeniden incelemeye yarayan JSON snapshot'ları
`data/raw/<source>/` altında tutulur. `data/` `.gitignore` kapsamındadır; gerçek
korpus GitHub'a gönderilmez. Quarantine payload'ları kişisel veri ve gereksiz
büyük metin açısından sınırlandırılmalıdır. Üretimde snapshot erişimi, saklama
süresi ve silme politikası KVKK gereksinimleriyle ayrıca yönetilmelidir.

## Tarihsel RAG davranışı

`POST /api/ai/answer` gövdesi ve `GET /api/legal/search` sorgusu isteğe bağlı
`as_of` tarihi kabul eder (`YYYY-MM-DD`). Tarih verilmezse yalnız `is_current`
kaynaklar aranır.

Tarih verildiğinde mevzuat yalnız şu şartlarla seçilir:

```text
effective_from <= as_of
ve (effective_to boş veya effective_to >= as_of)
```

`effective_from` bilinmiyorsa o sürüm tarihsel sonuca alınmaz. `version_date`,
çekim zamanı veya bugünün tarihi yürürlük başlangıcı yerine kullanılmaz. Bu
bilinçli olarak eksik cevap üretme pahasına kaynaksız hukuki sonuç üretmeme
kuralıdır. Mahkeme kararlarında yalnız güncel revision ve `decision_date <= as_of`
koşulu uygulanır.

RAG context ve citation kayıtları `version_date`, yürürlük aralığı,
`source_version` ve `revision` taşır. Böylece üretilen cevabın hangi sürüme
dayandığı sonradan denetlenebilir.

## Hata, rate limit ve CAPTCHA politikası

- 429 yanıtında `Retry-After` gözetilir; üstel backoff ve jitter uygulanır.
- Geçici 5xx yanıtları sınırlı sayıda tekrar denenir.
- 401/403 kalıcı yapılandırma/erişim hatası olarak değerlendirilir.
- CAPTCHA bypass edilmez; run `captcha_required`, adapter health `blocked` olur.
  Worker bu durumda süreçten çıkmaz; soğuma sonrası aynı imleçten yeniden dener.
- Varsayılan gecikme ve tur başına kayıt sınırları agresif değildir.
- Portal kullanım şartları, robots politikası, yeniden kullanım lisansı ve
  kişisel veri yükümlülükleri üretim ölçeğine çıkmadan hukukî olarak incelenir.

Bu uçlar resmî sitelerin kullandığı arayüzlerdir ancak genel ve değişmez bir API
taahhüdü değildir. Yanıt şeması değişirse canlı sisteme tahmin eklemek yerine
fixture/sözleşme testleri güncellenir ve uyumsuz kayıtlar quarantine edilir.

## Güvenlik ve operasyon sınırları

- `.env`, API anahtarları, JWT secret'ları, kullanıcı belgeleri ve corpus
  snapshot'ları Git'e girmez.
- Uygulama rolü korpus yazamaz; yönetim rolü yalnız migration/ingestion içindir.
- Quarantine ve worker yönetim uçları admin yetkisi gerektirir.
- Kaynağı olmayan hukuki iddia model promptuna bırakılmaz; retrieval ve citation
  doğrulaması kod katmanında uygulanır.

## Bilinen eksikler ve sonraki adımlar

1. Resmî Gazete künye doğrulaması aktiftir; madde bazlı değişiklik/yürürlük
   zinciri henüz tamamlanmamıştır.
2. Bedesten verilerinde birçok madde için açık yürürlük aralığı bulunmadığından
   tarihsel RAG kapsaması şimdilik düşüktür; sistem tarih tahmin etmez.
3. Danıştay tarih/daire bazlı aktiftir; serbest kelime araması bu transport
   sözleşmesinde yoktur.
4. AYM tarih filtresinin public arama sözleşmesi henüz sabitlenmediği için
   geriye dönük tarama sayfa cursor'uyla yapılır; PDF üretim ucu kullanılmaz.
5. Portalda kaybolan kayıtların güvenli “erişilemiyor” yaşam döngüsü için art
   arda doğrulama ve insan incelemesi politikası tamamlanmalıdır.
6. Büyük ölçekli korpus kapsamı daire, tarih penceresi ve arama filtresi bazında
   ölçülmelidir; tek bir “Yargıtay toplamı” yanıltıcıdır.

En mantıklı sonraki veri-katmanı işi, Resmî Gazete değişiklik belgelerini
madde sürümleriyle eşleyip `effective_from/effective_to` alanlarını kanıt
bağlantısıyla doldurmaktır. Bu, tarihsel RAG kapsamını güvenli biçimde büyütür.
