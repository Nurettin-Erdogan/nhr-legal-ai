# Yerel Qwen / DeepSeek karşılaştırması — 27.09.2026

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
