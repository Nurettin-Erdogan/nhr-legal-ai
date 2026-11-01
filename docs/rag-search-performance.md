# RAG arama performansı — 27 Eylül 2026

Bu adım yalnız RAG sorgularını değiştirir. Toplama, embedding işçileri, canlı
korpus kayıtları, veritabanı şeması ve kaynak doğrulama kuralları değiştirilmedi.

## Bulgular ve değişiklik

- Soru embedding'i ilk ölçümde 0,03–0,14 saniye sürdü; bu aşamanın darboğazı
  embedding değil metin aramasıydı. Cevap üretilmedi, yalnız aday araması ölçüldü.
- GIN metin indeksi mevcut. Soğuk/sıcak önbellek ve eşzamanlı disk yükü sonuçları
  belirgin etkiliyor. Doğrudan sorgu ile fonksiyon farkı tek başına plan hatası
  olarak yorumlanmamalı; 4 saniyelik sınırı artırmak çözüm olarak uygulanmadı.
- Python ilgililik kontrolündeki `artır` öneki PostgreSQL Türkçe sözlüğüne aynen
  verildiğinde `ar`a indirgeniyordu. SQL araması artık tam sözcük biçimlerini
  kullanıyor: `artırım`, `artırılması`, `artırma`. Atıf denetimi gevşetilmedi.
- Süre sorularında mevcut kanun/madde ipucu varsa ilk metin araması bunu da
  içeriyor. Örneğin konu sözcüklerine `2004` ve `67` ekleniyor; beklenen hukuki
  süre sorguya yazılmıyor. En az istenen aday sayısı kadar **ayrı ilgili belge**
  bulunmazsa kalan zamanla geniş konu araması yapılıyor. İki sorgu birlikte
  dört saniyelik metin arama bütçesini paylaşıyor; timeout durumunda eksiklik
  saklanmıyor. Tarihsel aramada tarih/sürüm filtreleri korunuyor.
- Bu aday seçimi tam sonuç sayımı değildir. `exhaustive=false` korunur.
  Araştırma sonuçlarını sayfalama uç noktası ayrı kalır. Doğrulanmamış kayıtlar
  aday olabilir, ancak bu değişiklik onları doğrulanmış yapmaz veya cevaba sokmaz.

## Canlı, salt okunur A/B ölçümü

Aynı soru embedding'i ve canlı korpusla sırayla eski/yeni/eski/yeni sorgular
çalıştırıldı. Portal doğrulaması, LLM üretimi ve kayıt güncellemesi yapılmadı.
Süreler aday aramasına aittir; kullanıcıya cevabın toplam süresi değildir.

| Soru | Eski arama (sn) | Yeni arama (sn) | Yeni havuzdaki ayrı belge |
| --- | --- | --- | --- |
| Kira/TÜFE artışı | 4,424 / 4,034 | 2,293 / 0,893 | 48 (30 resmî etiketli, 18 bekleyen) |
| Ortak velayet | 0,799 / 0,403 | 0,423 / 0,407 | 29 (12 resmî etiketli, 17 bekleyen) |
| İtirazın iptali süresi | 4,380 / 4,227 (iki timeout) | 3,666 / 1,441 | 48 (12 resmî etiketli, 36 bekleyen) |

Ortak velayet sorgusu değişmedi; küçük süre farkı kod iyileştirmesi iddiası
değildir. Kira eski ilk denemede timeout, ikinci denemede başarılıydı. Bu küçük
örneklem bir SLA veya genel hız garantisi değildir. Disk baskısında timeout hâlâ
mümkündür. İlgililik filtresinden geçmek de hukuki doğruluk kanıtı değildir.

## Kalan işler

1. İlgililik/reranking kalitesini daha geniş, etiketlenmiş soru setinde ölçmek.
2. Doğrulama ve model üretimini de kapsayan uçtan uca gecikmeyi ayrıca ölçmek.
3. Soğuk önbellek/disk yükü altında p50/p95 ölçümü yapmak; gerekirse ayrı arama
   altyapısını değerlendirmek. Şu aşamada çalışan kolektörler durdurulmadı.

Regresyonlar: `tests/test_rag_focused_search.py`; gerçek Türkçe sözlük testleri
yalnız izole `NHR_TEST_DATABASE_URL` ile çalışır.

İzole release kopyasında CI şemasıyla tam Python paketi: **521 geçti, 1 atlandı**.
Test için açılan ayrı veritabanı test sonunda kaldırıldı; canlı korpusa yazılmadı.

## Ek ölçüm: kıdem tazminatı şartları

Genel hak kazanma/şart/koşul soruları için `1475` ve `14` ipucu da odaklı ilk
arama kapsamına alındı. Kanundaki bir sonuç veya süre sorguya eklenmez. Açıkça
emsal/içtihat isteyen veya delil/ispat soran sorular geniş konu aramasını korur.
İlgili ayrı belge sayısı yetersizse mevcut ortak dört saniyelik bütçe içinde
geniş aramaya dönülür. Semantik arama, tarih filtreleri, bekleyen kayıtların
aday olabilmesi ve cevap öncesi kaynak kontrolü değişmedi.

Salt okunur metin araması A/B denemesinde kıdem sorusunun eski yolu iki kez
4,07–4,08 saniyede zaman aşımına uğradı (yalnız doğrudan bulunan kanun kaldı).
Odaklı yol 2,47 ve 0,79 saniyede 45 ayrı belge getirdi; bunların 9'u korpusta
resmî etiketliydi. Bu iki ölçüm genel hız veya recall garantisi değildir.
Kira sorusundaki deney aday dağılımını değiştirdi ama tutarlı bir hız kazancı
göstermedi; bu yüzden kira aramasına bu daraltma uygulanmadı.

Ardından gerçek embedding + arama + yerel `qwen3.5:4b` denemesi yapıldı:

| Soru | Embedding + arama (sn) | Üretim + kaynak denetimi (sn) | Sonuç |
| --- | --- | --- | --- |
| Kıdem şartları | 12,43 | 1,83 | Semantik ve metin araması timeout; mevcut kanuna dayalı cevap |
| Kira/TÜFE | 4,02 | 0,62 | Arama tamamlandı; TBK 344 kaynaklı cevap |
| İtirazın iptali süresi | 4,61 | 0,92 | Arama tamamlandı; İİK 67 kaynaklı cevap |
| Ortak velayet | 2,23 | 1,76 | Arama tamamlandı; iki kaynağa dayalı cevap |

Dört cevap da programatik kaynak denetimini geçti; bu sonuç bağımsız hukuki
doğruluk değerlendirmesi değildir. İlk satır, yük altında odaklı sorgunun da
timeout olabildiğini gösterir. Süreler API'nin toplam yanıt süresi değildir:
portal doğrulaması, sohbet kaydı ve açıklayıcı yeniden yazım bu smoke testinde
çalıştırılmadı. Test yalnız mevcut resmî etiketli bağlamları modele verdi;
bekleyen hiçbir kayıt bu nedenle doğrulanmış sayılmadı. Toplama işçilerine ve
canlı korpus kayıtlarına müdahale edilmedi.

Bu ek değişikliğin izole CI şemasıyla Python regresyon sonucu: **547 geçti,
1 atlandı**. Yalnız geçici test veritabanı test sonunda kaldırıldı.
