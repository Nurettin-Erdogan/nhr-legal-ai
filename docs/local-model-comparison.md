# Yerel model karşılaştırmaları

## 09.10.2026: bu donanımda daha güçlü bir yerel model var mı?

**Sonuç: hayır.** RTX 3050 6 GB ekran kartına tam sığan en büyük güncel model zaten kullanılan `qwen3.5:4b`. Denenen üç
seçeneğin hiçbiri onu geçmedi; üretim modeli değiştirilmedi.

| Seçenek | Kaynak cümlesi seçimi (15 etiketli soru) | Uçtan uca (20 soru) | Süre | Karar |
|---|---|---|---|---|
| `qwen3.5:4b`, düşünme kapalı (**mevcut**) | 13/15 tam, 16/18 etiket cümlesi; karışık sırada 12/15, 15/18 | 20/20 kaynaklı, 19/20 beklenen kanun | seçim 2,2 sn; cevap ortanca 12 sn, en uzun 24 sn | kalır |
| `qwen3.5:4b`, düşünme açık | ilk 3 soruda geçerli seçim **yok** (2 048 belirteçlik düşünce, cevap gelmeden kesildi) | ölçülmedi | soru başına 50-55 sn | kullanılamaz |
| `deepseek-r1:8b` (5,2 GB; kartta %70'i) | 15 soruyu 19 dakikada bitiremedi | ölçülmedi | — | kullanılamaz |
| `qwen3.5:9b` (5,6 GB dosya; bellekte 6,25 GB, kartta %57'si) | 14/15 tam, 17/18; karışık sırada 12/15, 15/18 | **18/20** kaynaklı, **16/20** beklenen kanun | seçim 5-6 sn; cevap ortanca 21 sn, en uzun 50 sn | geçilmedi (silindi) |

Okuma:

- Daha büyük model yalnız seçim adımında bir soru fazla tutturdu, ama karta sığmadığı için her model çağrısı ~2,5 kat
  yavaşladı ve uçtan uca **daha kötü** çıktı (iki soru "yeterli bilgi yok" ile bitti, cevap süresi iki katına çıktı).
- İki model de aynı zor soruyu kaçırıyor: "haksız fesihte hangi tazminatlar" sorusunda İş Kanunu m. 17'deki ihbar tazminatı
  cümlesini ("Bildirim şartına uymayan taraf … tazminat ödemek zorundadır") seçmiyorlar. Cümleyi tek başına sorunca da
  (aşağıda) "hayır" diyorlar: bu, hukuk bilgisi gerektiren bir eşleme ve küçük modelde yok.
- **Tek tek sorma** (her kanun cümlesi için "bu cümle soruyu yanıtlayan bir kural koyuyor mu?"): `qwen3.5:4b` ile 18 etiket
  cümlesinin 15'ine "evet", etiket olmayan 72 cümlenin 23'üne de "evet" (soru başına 2,3 sn ek). Liste seçiminden iyi
  değil; uygulamaya alınmadı.
- Ollama kütüphanesindeki güncel modellerin çoğu 27B ve üstü ya da bulut modelidir (bakıldı: 09.10.2026). 9B sınıfı karta
  tam sığmıyor (`qwen3.5:9b` ile ölçüldü; `nimble`, `ornith` 9B denenmedi, aynı sınırı yaşarlar). 3-4B sınıfındaki başka
  adaylar (`tev1:4b`, `granite4.2:3b`) **ölçülmedi**.

Yerel modelle devam kararı (09.10.2026) üzerine, modelin kaçırdığı asıl kural cümlesi konu tablosundan güvenceye alındı
(`docs/assistant-answer-quality.md`, "asıl kural cümlesi güvencesi"); bu adımla aynı 15 soruda uygulamanın cevabı 15/15'e
çıktı. Bu, modelin değil tablonun kapsamıdır: yukarıdaki model karşılaştırması o adım **olmadan** yapılmıştır.

Demek ki cevap kalitesinde belirgin sıçrama için ya **daha büyük ekran kartı** (27B sınıfı model ~17-20 GB ister; kod
değişmez, yalnız `AI_MODEL` değişir) ya da **bulut modeli** gerekir. Bulut, müvekkil verisi bakımından bir KVKK kararıdır
(`docs/yayin-plani.md`); sağlayıcı katmanı ayrı tutulduğu için eklenmesi küçük iştir ama karar verilmeden yazılmadı.

### Yöntem

`scripts/bench_selection_models.py`: 15 soru için uygulamanın gerçek adayları bir kez dondurulur (arama + konu maddesi +
aday cümleler + uygulamadaki istemin aynısı); her model aynı istemi alır. Etiket, cevabı taşıyan kanun cümlesinin ayırt
edici parçasıdır ve korpustaki resmî metinden yazılmıştır (18 cümle; ör. işe iade: m. 18'in ilk cümlesi + m. 20'nin
arabulucu cümlesi). "Karışık sıra": aynı adaylar sabit tohumla karıştırılıp yeniden numaralanır; model cümleyi yerinden
değil içeriğinden bulmalıdır. Sıcaklık 0, bağlam 4 096 (düşünmede 8 192), çağrı başına en çok 150 sn.

Sınırlar: 15 soru azdır ve çoğu iş hukukudur; etiketleri tek kişi yazdı; seçim adımı ölçülür, açıklama metninin
okunabilirliği ölçülmez. Ölçüm sırasında embedding işçisi ve veri çekimi çalışıyordu. Uçtan uca 20 soruda `qwen3.5:4b`
sonuçları bir gün önceki koşudandır (aynı kod, daha sıcak disk).

Ölçüm tuzağı: iki süreç aynı modeli farklı bağlam boyuyla çağırırsa Ollama modeli her çağrıda yeniden yükler (50-70 sn);
durdurulan bir komut zincirinin sıradaki halkası kendiliğinden başlayıp ölçümü böyle bozdu.

Bu ölçüm sırasında konu tablosunda iki boşluk bulundu ve kapatıldı: "yıllık ücretli **izne**" (ünlü düşmesi) ve "iş
uyuşmazlıklarında arabulucu" soruları tabloyla eşleşmiyordu (`tests/test_statute_hint_topics.py`).

```powershell
.\.venv\Scripts\python.exe scripts/bench_selection_models.py freeze
.\.venv\Scripts\python.exe scripts/bench_selection_models.py run qwen3.5:4b nothink qwen4b
.\.venv\Scripts\python.exe scripts/bench_selection_models.py run qwen3.5:4b nothink qwen4b shuffle
```

Ham sonuçlar yerelde `data/benchmarks/selection-models-20261009/` altındadır (korpus metni içerir, depoya girmez).

## 27.09.2026: Qwen / DeepSeek

## Sonuç

Bu küçük, yerel **kaynak cümlesi seçimi** testinde `qwen3.5:4b` daha iyi ilk aday.
Aktif üretim modeli değiştirilmedi; `.env` hâlâ DeepSeek kullanıyor. Bu rapor genel
Türk hukuku uzmanlığı veya serbest metin üretimi sıralaması değildir.

| Ölçüm | DeepSeek R1 8B | Qwen3.5 4B |
|---|---:|---:|
| Gerçek kaynaklı 3 soru × 2 tur medyan üretim | 4,605 sn | 1,282 sn |
| İcra sorusu, iki tur | 7,681 / 2,901 sn | 1,155 / 0,929 sn |
| Ortak velayet, iki tur | 16,046 / 3,026 sn | 1,296 / 1,267 sn |
| Kıdem, iki tur | 4,483 / 4,727 sn | 1,449 / 2,216 sn |
| Bu 6 gerçek kaynaklı çağrıda metin/atıf kontrolü | 6/6 | 6/6 |
| Güçlendirilmiş 4 sentetik kontrol × 2 tur | 6/8 | 8/8 |
| Yetersiz kaynakta doğru kaçınma (sentetik) | 0/2 | 2/2 |

Yaklaşık 3,6 kat medyan hız farkı sadece ölçülen model aşamasına aittir. Arama,
portal doğrulaması, model yüklemesi, HTTP/SSE ve kalıcılık süreleri dahil değildir.
Arka plan işçileri durdurulmadı; bunlar laboratuvar koşullarında ölçümler değildir.
Özellikle DeepSeek'in ilk turu ikinci turundan daha yavaştı.

## Düzenek ve sınırlar

- RTX 3050 Laptop 6 GB; Ollama 0.34.2; her ikisi Q4_K_M.
- 4096 bağlam, en fazla 512 çıktı tokenı, düşünme kapalı, sıcaklık 0.
- Mevcut uygulama provider'ı ve `generate_grounded_answer` / `verify_answer`
  kullanıldı. DeepSeek'e mevcut R1 raw şablonu, Qwen'e chat şablonu uygulandı.
  Bu nedenle ölçüm soyut model değil, model + mevcut entegrasyon karşılaştırmasıdır.
- DB yalnız okunur işlemle sorgulandı. Sadece `official` genel hukuk kaynakları
  donduruldu; hiçbir kullanıcı belgesi, pending kaynak veya portal isteği yok.
- Aynı kaynak kimlikleri/metinleri SHA-256 ile sabitlendi. Üretim sırasında DB'ye
  tekrar gidilmedi; sohbet kaydı veya yanıt önbelleği kullanılmadı.
- ABBA sırası, her blok öncesi ısınma. İki model eşzamanlı çalıştırılmadı.
- Qwen ilk ısınması 39,145 sn, sonraki 4,969 sn. DeepSeek 4,605 / 17,746 sn.
  Bunlar daima soğuk yükleme ölçümü değildir; başlangıçtaki bellek durumu farklıdır.
- DeepSeek çalışma belleği ~7,78 GB, GPU payı ~4,21 GB; Qwen ~3,13 GB ve tamamı GPU'da.
  DeepSeek bloklarında Nomic embedding modeli de yüklüydü; Qwen bloklarında değildi.
  Bellek yerleşimi Ollama'nın yönetimidir, çalışan embedding işçileri durdurulmadı.
- 6 gerçek sorunun 3'ü aramada 15 saniye civarında zaman aşımına uğradı: yıllık
  izin, idari işlem iptali, AYM bireysel başvuru. Bunlar iki modele de verilmedi;
  model başarısı/başarısızlığına eklenmedi. İcra araması 12,083 sn,
  velayet 1,049 sn, kıdem 1,713 sn sürdü.
- İlk ana koşuda kaynak yetersizliği kontrolü cümle filtresinde elendiği için
  model çağrısı sayılmadı. Talimat saldırısı da bu koşuda modele ulaşmıyordu.
  Bu iki kontrol güçlendirildi ve ayrı dosyada yeniden çalıştırıldı; nihai kontrol
  puanları yalnız `controls-results.json` içindeki dört kontrolü esas alır.
- Toplam 40 ölçülen üretim çağrısı: ana koşuda 24, güçlü kontrollerde 16.
  Isınma/aktif modeli yeniden belleğe alma çağrıları buna dahil değildir.
- Test edilen çalışma ağacında önceden var olan, commit edilmemiş provider/RAG
  değişiklikleri bulunuyor; sadece HEAD numarası bu deneyi tekrar üretmeye yetmez.

## Cevapların incelemesi

- **İcra:** İki model aynı, süreyi ve başlangıcı içeren kaynak cümlesini seçti.
- **Ortak velayet:** Qwen daha dar bir ilgili pasajı seçti. DeepSeek ilk turda
  daha fazla somut olay pasajı, ikinci turda tek pasaj seçti. Bunlar kapsamlı bir
  hukukî şartlar analizi değildir; somut olayı genel kural gibi sunma riski sürer.
- **Kıdem:** İki model de yeterli cevap vermedi. Getirilen kaynaklar ağırlıkla
  emekli ikramiyesi/hizmet birleştirmesi bağlamındaydı. Qwen maddeye işaret eden
  iki tekrarlı cümle seçti; DeepSeek ilk turda başka bağlamdan parçalar da seçti.
  Atıf kontrolünün geçmesi, sorunun doğru veya tam yanıtlandığını göstermez.
- **Yetersiz kaynak kontrolü:** Metinde itiraz süresi bulunurken harç miktarı
  soruldu. Qwen iki turda da boş kanıt seçimiyle kaçındı; DeepSeek iki turda da
  ilgisiz süre cümlesini seçti. DeepSeek para miktarı uydurmadı ama soruyu yanıtlamadı.
- **Güçlü talimat saldırısı / istisna / destekli kural:** İki model de iki turda
  beklenen seçimi yaptı. Bu az sayıdaki test genel güvenlik garantisi değildir.

Sonraki öneri: Qwen'i kontrollü pilotta kullanmak; ardından arama zaman aşımı,
konu alakasını ölçen kontroller ve kıdem gibi sorularda doğru mevzuatın bulunmasını
düzeltmek. Yalnız model değiştirmek bu sorunları çözmez. Nihai kalite kararı için
uzman etiketli, daha geniş ve ayrı tutulmuş bir test seti gerekir.

## Yeniden çalıştırma

Model kurulumu dışında testler tamamen yereldir. Korpus/ingestion veya `.env`
değiştirilmez. Her yeni koşuda farklı çıktı yolu kullanın; script eski sonuçları
üzerine yazmayı reddeder.

```powershell
.\.venv\Scripts\python.exe scripts/compare_local_rag.py freeze --fixture data/benchmarks/new/contexts.json
.\.venv\Scripts\python.exe scripts/compare_local_rag.py compare --fixture data/benchmarks/new/contexts.json --output data/benchmarks/new/results.json
.\.venv\Scripts\python.exe scripts/compare_local_rag.py controls --fixture data/benchmarks/new/controls.json
.\.venv\Scripts\python.exe scripts/compare_local_rag.py compare --fixture data/benchmarks/new/controls.json --output data/benchmarks/new/controls-results.json
```

Bu koşunun ham sonuçları ve genel hukuk kaynak parçaları yerelde
`data/benchmarks/local-models-20260927/` altında tutulur; GitHub'a korpus metni
gönderilmez. GitHub'a yalnız test aracı, çevrimdışı testler ve bu rapor eklenir.

Model digest'leri:

- DeepSeek: `6995872bfe4c521a67b32da386cd21d5c6e819b6e0d62f79f64ec83be99f5763`
- Qwen: `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd`
