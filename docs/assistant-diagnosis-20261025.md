# Asistan: embedding sonrası ölçülmüş sorunlar

## Kapsam ve yöntem

25 Ekim 2026. Üç sabit genel soruda iki tur kaynak araması, ek kira araması,
aynı kira sorusunda iki gerçek bulut üretimi ve hedefli çevrimdışı testler.
`scripts/diagnose_assistant.py` tekrar üretim aracıdır. Dosyadan UTF-8 okunan
sorular kullanıldı; PowerShell stdin kodlamasıyla bozulmuş ilk keşif koşuları
geçerli sonuç sayılmadı. İç işlem hattında `user_id=None`: kaydedilmiş sohbet,
kullanıcı belgesi, erişim listesi veya RLS politikası değiştirilmedi.

Bu tur ürün davranışı değiştirilmedi; diagnostic betiği eklendi. DB bakım,
indeks oluşturma, API yeniden başlatma, `.env` değişikliği ve commit yapılmadı.

## 1. Kısmi taramanın gerçek nedeni

| Soru | İlk arama | İkinci arama | Metin kolu |
| --- | --- | --- | --- |
| Kira artışı: mevzuat ve kararlar | 3,87 sn | 1,32 sn | İlkinde timeout_then_tiered, ikincide ok |
| İşten çıkarılma hakları | 5,45 sn | 5,29 sn | İkisinde timeout_then_tiered |
| Ortak velayet koşulları | 1,03 sn | 1,14 sn | İkisinde ok |

Kira sorusunun vektör kolu yaklaşık 0,11–0,12 sn. İlgili TBK 344/345 bulunuyor.
Uyarı embedding yokluğundan değil; full-ranking metin sorgusu 2,5 saniyelik ilk
bütçeyi aşınca sınırlı katmanlı aramaya geçildiği için `partial=true` oluyor.
Bu yol yalnız bir görsel sorun değildir: adayların tamamı aynı şekilde
sıralanamadığından sonuç kapsamı değişebilir. Uyarı gizlenmemeli.

Runtime DB'deki `legal_rag_current_lexical_hits` gövdesi, sözcük eşleşmelerini
puanlayıp sıraladıktan sonra kaynak uygunluk denetimini yapıyor. Kira ve iş
niyeti tsquery'leriyle aynı puanlama/sıralama çekirdeğini çalıştıran salt okunur
EXPLAIN ANALYZE denemeleri 8 saniyede iptal edildi. Bu deney fonksiyonun bütün
join planını temsil etmez, fakat maliyetin LLM'den önce de oluştuğunu gösterir.

## 2. Büyük beklemenin ana nedeni her zaman arama değil

Aynı kira sorusunun iki gerçek model koşusu:

| Koşu | Retrieval | LLM/onarım | Sonuç |
| --- | --- | --- | --- |
| 1 | 0,904 sn | 109,889 sn | numeric_polarity / number_or_unit, grounded=false |
| 2 | 0,858 sn | 103,947 sn | Onarım + semantic_repair, grounded=true |

İkinci koşuda kaynak araması tamamlansa da cevap yaklaşık 105 saniye sürdü.
`repair_attempted` ve `semantic_repair_attempted` birlikte set edildi. Bu
tek bir model çağrısı değildir; üretim/onarım/denetim zincirinin toplamıdır.
`last_usage` yalnız son çağrının kullanımını gösterir: onu tüm zincirin token
ve maliyet toplamı diye okumamak gerekir.

İlk koşudaki sayı/birim reddinin hangi cümlede oluştuğu eski telemetry ile
belirlenemedi. İkinci koşudaki trace, aynı reddi tekrar üretmedi; farklı
mekanik kapsam bulguları ve semantik onarım görüldü. Dolayısıyla ilk ret için
"kesin yanlış alarm" veya "kesin model hatası" denilemez.

## 3. Kritik destek denetimi açığı: kararın konuşan makamı

İkinci koşuda cevap, Yargıtay 12. HD E.2022/13237 K.2023/1432 kaydına dayanarak
"Yargıtay ... kira sözleşmesinde yıllık artış oranı belirlenmemişse ... karar
vermiştir" anlamında bir sonuç üretti ve bağımsız denetçi onayladı.

Ancak iddiaya bağlanan kanıt ünitesi açıkça **İLK DERECE MAHKEMESİ KARARI**
başlığıyla başlıyor; alt mahkemenin gerekçesini aktarıyor. Kayıt künyesinin
Yargıtay olması, metindeki her değerlendirmenin Yargıtay'ın kendi hukuki
görüşü veya nihai hükmü olduğu anlamına gelmez. Sonuç kısmı başka yerde bu
görüşü onaylıyor olsa bile mevcut iddia-kanıt eşleştirmesi bunu kanıtlamıyor.

`case_scope_omitted` ve `maximum_omitted` bulguları üretildi. Uzun kanıt
ünitelerinde bu bulgular bağımsız denetçiye not olarak bırakılıyor; bu koşuda
denetçi yine onay verdi. Bu, hukuki doğruluk kontrolünün yeterli olduğu
iddiasını çürütür. Çözüm kaynak kuralını kaldırmak değil; taraf iddiası, ilk
derece gerekçesi, kanun alıntısı ve üst mahkeme gerekçesi/sonucunu ayırıp
makam atfını kod tarafında da bağlamaktır.

## 4. Son kaynak seçimi ve parça bütünlüğü

Kira sorusunda son sekize TBK 344/345 ve Yargıtay yanında Sayıştay, KDK ve
kamu tesislerinin kira karşılığı yaptırılması hakkındaki özel yönetmelik
girdi. Genel soru hangi kira türünün kastedildiğini belirtmediğinden bunlar
otomatik olarak "yanlış kaynak" sayılamaz; fakat farklı rejimlerin bağlam
ayırt edilmeden aynı genel cevaba girmesi riski var.

Seçilen sekiz kaynağın dördü `_source_views` bütünlük denetimine ilk hâliyle
uygun değildi ve kırpılabilir bulundu. Bu "dört kaynak yok" demek değildir;
sondaki yarım cümlenin çıkarılması/bağlamın daralması ve parçanın gerçekten
hangi bölüme ait olduğunun takibi gerekir. İlgili kararın komşu parçası ve
sonuç bölümünün kontrollü getirilmesi değerlendirilmelidir.

## 5. DB bakım ve bellek sinyalleri (tahmini istatistik)

- `legal_chunks`: 53 GB, yaklaşık 29,56 milyon canlı satır.
- Metin GIN indeksi: 31 GB. Binary HNSW: yaklaşık 6 GB.
- `shared_buffers=6GB`, `effective_cache_size=9GB`.
- `n_dead_tup` tahmini yaklaşık 15,73 milyon.
- Son autoanalyze kaydı 24 Ekim 2026; bu tur ANALYZE/VACUUM çalıştırılmadı.

Bunlar soğuk/sıcak arama farkıyla uyumlu bakım/bellek sinyalleridir; ölçülmüş
fiziksel bloat miktarı veya tek başına kök neden kanıtı değildir. Özellikle
`VACUUM FULL`/REINDEX gibi ağır işlemler otomatik uygulanmamalı. Önce normal
istatistik/bakım ihtiyacı, eşleşme seçiciliği ve sorgu planı incelenmeli.

## Test ve sonuç

Arama/sentez/hafıza destek denetimi hedefli paketi: **284 geçti**.
Bu testlerin büyük kısmı fixture/model taklidi kullanır. Canlı gözlemdeki
makam-atıf hatasını yakalamadıkları için tek başına ürün kabulü sayılmazlar.

Öncelik: (1) yanlış makam atfını engelleyen canlı örnekten regresyon,
(2) tam karar bağlamı + kaynak sıralaması, (3) onarım zincirinin çağrı bazında
süre/maliyet ölçümü, (4) metin araması planı ve embedding sonrası DB bakım
planı. Embedding'in yeniden yapılması veya kaynak denetiminin kapatılması
bu bulgulara çözüm değildir.
