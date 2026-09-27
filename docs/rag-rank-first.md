# RAG metin araması: sıralama öncelikli sorgu

2026-09-27 ölçümünde 4 saniyelik metin arama sınırı, kira/ortak velayet/kıdem
sorularında doluyordu. Aynı sorgular sıcak önbellekte çok daha hızlıydı;
disk okuma yükü sonuçları önemli ölçüde değiştiriyor. Anlamsal sorguda mevcut
HNSW indeksinin kullanıldığı EXPLAIN ile doğrulandı; embedding işçileri durdurulmadı.

`028_rank_first_lexical.sql`, mevcut kamuya açık hukuk korpusu fonksiyonunu
aynı imzayla değiştirir. Önce GIN eşleşmeleri sıralanır; sonra sıralı sonuçların
güncellik/silinme/kaynak uygunluğu kontrol edilir. İstenen sonuç sayısına
ulaşıldığında metadata okumaları durur. Uygun olmayan yüksek sıralı kayıtlar
elenir ve daha aşağıdaki uygun kayıtlarla doldurulur. Keyfî ilk N eşleşme kesimi
yoktur; `NULL` limit kullanan eski araştırma çağrısı tüm eşleşmeleri alabilir.

Sabit SQL metni `EXECUTE ... USING` ile parametrelenir, sorgunun gerçek seçiciliğine
göre planlanır. [PostgreSQL 16 belgesi](https://www.postgresql.org/docs/16/plpgsql-statements.html#PLPGSQL-STATEMENTS-EXECUTING-DYN)
bu yöntemin planı her çalıştırmada yeniden ürettiğini açıklar. Kullanıcı SQL'i
birleştirilmez. SECURITY DEFINER yalnız public hukuk tablolarına erişir; kullanıcı
belgelerini okumaz. Üçüncü taraf kayıtların doğrulanmış sayılma kuralları değişmez.

Soğuk disk için odaklı + geniş metin aramasının **ortak** üst bütçesi 8 saniyedir.
Odaklı dal 1 saniye kullanırsa geniş dal yalnız kalan 7 saniyeyi alır. Bir dal
gerçekten zaman aşımına uğrarsa `partial=true` ve kullanıcı uyarısı korunur.
Bu değişiklik tüm soruların/tüm yük koşullarının zaman aşımından muaf olduğunu
veya top-K cevap bağlamının tüm ilgili belgeler olduğunu iddia etmez.

Genel kira artışı sorularında mevcut 6098/344 konu eşlemesi, ilk arama için de
kullanılır. Yeterli farklı ilgili aday yoksa kalan ortak bütçeyle geniş arama
yapılır. Açık içtihat/emsal veya delil talepleri daraltılmaz. Bu bir sıralama ipucudur,
hukuki cevap değildir; getirilen metin ve atıf kontrolü aynı kalır.

## Doğrulama

CI migration'ı uygular; tam sonuç/rank eşdeğerliği, uygun olmayan yüksek sıralı
kayıtların altındaki sonuçların bulunması ve runtime rolünün kaynak sınırları
test edilir. Üretim korpusuna test kaydı eklenmez.

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_rag_search.py --repeats 2 --concurrency 2
```

Bu komut yalnız aramayı ölçer; LLM cevap süresi, resmî portal doğrulaması ve sohbet
kaydı dahil değildir. Her bağlantı READ ONLY'dir. `failed_or_partial` sıfır değilse
komut hata kodu verir. Soğuk disk/sıcak önbellek ve eşzamanlı yük farklarını raporla;
tek sıcak koşunun sonucunu genel hız garantisi olarak sunma.

Yerel son ölçüm (3 soru × 2 tur, 2 eşzamanlı arama): 6/6 tamamlandı,
`failed_or_partial=0`, medyan 0,558 sn, maksimum 0,772 sn. Bu ölçüm sıcak
önbellek etkisi içerir. Daha önceki geniş kira araması aynı eşzamanlı testte
iki kez 8 saniyede kesilmişti; referanslı ilk arama eklenmeden sorun bitmiş sayılmadı.

Eski sohbet mesajlarının kaydedilmiş `retrieval_partial` değeri geriye dönük
değiştirilmez. Yeni davranış, yeni soruyla test edilir; eski uyarılar silinmez.
