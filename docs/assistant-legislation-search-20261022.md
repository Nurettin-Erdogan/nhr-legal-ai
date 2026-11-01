# Asistan: yarım parçalar, alıntı yedeği ve mevzuat araması — 22.10.2026

## Bulgu

DeepSeek Flash'a bağlanan doğal cevap hattı (bkz. `docs/assistant-natural-grounding-20261021.md`) canlıda genel hukuk
sorularının çoğuna "Bu soruya kaynaklarla doğrulanmış bir cevap oluşturamadım" diyordu: 7 genel sorudan 5'i, standart
20 soruluk ölçümde (`scripts/eval_live_answers.py`) 0/20 kaynaklı cevap. Üç neden vardı.

1. **Yarım parça bütün cevabı düşürüyordu.** `synthesis._source_views` kaynaklardan biri cümle ortasında bitince
   (karar parçaları hep öyle biter; mevzuatta "(Değişik fıkralar: …)" notu ya da sonraki bölüm başlığı) sentezi hiç
   çalıştırmadan `source_shape` ile reddediyordu.
2. **Harfiyen alıntı tutmayınca cevap kalmıyordu.** Yazar model kanıt cümlesini kaynaktan birebir kopyalamayınca (`evidence`)
   ya da biçim bozulunca (`draft_shape`) cevap tamamen düşüyordu; daha önce 20/20 kaynaklı olan alıntı yoluna dönülmüyordu.
3. **Asıl madde aday bile olmuyordu.** Anlam araması 7,8 M parçalık tek dizinde yapılıyor; mevzuat bunun %1,4'ü. "Haksız
   fiil … zamanaşımı" sorusunda en yakın adayların hepsi karardı, TBK m. 72 hiç gelmiyordu. Sözcük araması da bütün
   terimleri birlikte aradığından ("doğan", "davası" maddede geçmiyor) maddeyi bulamıyordu.

Ayrıca: 21 Ekim'de API `.local/start_api_output_policy_20261021.py` ile açılmıştı; `.local/restart_api.ps1` o süreci
durdurmadığı için yeni süreç portu alamıyor (`.local/api.err.log`: WinError 10048) ve eski kod çalışmaya devam ediyordu.

## Değişiklik

- **Kuyruk kırpma** (`synthesis._without_cut_off_tail`): kaynak, son yarım cümlesi atılmış hâliyle kullanılır; yazar da
  denetçi de o kuyruğu görmez. Mevzuatta yalnız değişiklik notu ve kısa numaralı başlık ("II. Rücu isteminde",
  "C. Karar") kırpılır; kararlarda kuyrukta koşul, istisna, olumsuzluk, "aksi/tarafından" ya da sayı yoksa. Aksi hâlde o
  parça cevaba hiç girmez ama diğer parçalarla cevap yazılır. Talimat sızdırma içeren kaynak kırpılarak "temizlenmez".
  Kullanıcı belgesinde eski katı davranış aynen geçerlidir.
- **Alıntı yedeği** (`pipeline._MECHANICAL_SYNTHESIS_REJECTIONS`): sentez denetçiye varmadan mekanik bir nedenle
  düşerse (`evidence`, `draft_shape`, `numeric_polarity`, `source_shape`, `budget`) doğrulanmış alıntı yolu ve kısa
  madde özeti çalışır (`answer_mode=synthesis_then_quotes`, önbelleğe alınmaz). Bağımsız denetçinin reddettiği
  (`checker`) taslakta bu yol açılmaz; "oluşturamadım" korunur.
- **Mevzuat için ayrı anlam araması** (migration `060_legislation_vectors.sql`, init `061`): mevzuat parçalarının
  vektörleri `legislation_chunk_vectors` tablosunda kendi HNSW dizinine sahip (109.152 parça, 86.434 madde). Tablo bir
  kopyadır; `legal_chunks` üzerindeki tetikleyici vektör değişince günceller (yalnız mevzuat, yalnız 768 boyut; yazmayı
  asla engellemez). RLS: okuma `legal_chunks` ile aynı kural; `nhr_runtime` yazamaz. Arama kolu
  (`retrieval.LEGISLATION_SEMANTIC_SQL`, ~0,3 sn) sonuçları `legal_sources`'a geri bağlayıp aynı resmî/güncel/sürüm
  süzgecinden geçirir; en yakın 40 maddeden soru terimlerine en uygun ikisi, diğer kollardan gelen maddeleri çıkarmadan
  listeye eklenir. Bulut yazar için cevap kaynağı sınırı 6'dan 8'e çıkar (yerel model 6'da kalır).
- Kurulum klasörüne eksik olan `060_corpus_counters.sql` eklendi (21 Ekim migration'ı 059).

## Ölçüm

| | Sabah | Yarım parça + yedek | + mevzuat araması |
| --- | --- | --- | --- |
| 20 soruluk ölçüm, kaynaklı | 0/20 | 19/20 | 18/20 (ortanca 31 sn) |
| "Haksız fiil zamanaşımı" | oluşturamadım | oluşturamadım | TBK m. 72 ile doğal cevap, 5,7 sn |
| "Kiracı kirayı ödemezse" | oluşturamadım | TBK m. 315 + 352 | TBK m. 315 + 352 |
| "Boşanmada nafaka" | oluşturamadım | 2 Yargıtay kararı | TMK m. 169 + Yargıtay |

## Açık

- **Hız:** ortanca ~30 sn (18 Ekim yerel modelle 12 sn): doğal taslak + düzeltme + yedek + özet ayrı model çağrıları.
- **Gündelik anlatım:** "haklı sebep olmadan işten çıkarırsa" sorusu İş K. m. 17/18/21'e ulaşmıyor (eş anlam:
  "işten çıkarmak" = "fesih"); kaynak eksikliği bildirimi dönüyor.
- Gömme modeli (nomic-embed-text) Türkçe hukuk dilinde zayıf; mevzuat için daha güçlü çok dilli bir model yalnız bu
  109 bin parçaya uygulanabilir (kopya tablo buna hazır).

## İkinci tur (aynı gün): hız ve tutarlılık

Ölçüm (`profile_answer`): yavaş cevapların süresi ilk taslağın mekanik retle düşmesi + 8-26 sn'lik düzeltme çağrısı +
yedek yoldan geliyordu; düzeltme ölçülen hiçbir soruda başarılı olmadı.

- Mevzuat ilk cümlesindeki başlık ve tarihli değişiklik notu yapısal sayılır ("Yıllık ücretli izin hakkı … Madde 53 -",
  "(Değişik birinci fıkra: 29/7/1983 - 2869/3 md.)"); tarihsiz not ve başka maddenin etiketi yine alıntılanmalı.
- Uzun sayım cümlesinin bir kısmını alıntılayan kanıt, o cümlenin TAMAMINA bağlanır; sayı/olumsuzluk/koşul/istisna
  kontrolleri ve denetçi iddiayı tam cümleyle karşılaştırır (koşul atlayan iddia yine düşer). Yalnız ≥40 karakterlik ve
  cümleden en az 80 karakter kısa alıntılar.
- İlk taslakta mekanik kontrolden geçemeyen iddia atılır, kalanlar denetçiye gider (`dropped_claims`). Denetçinin
  reddettiği iddia atılır, kalanlar BİR KEZ daha denetlenir (`checker_dropped`); hiçbir iddia yeniden yazılmaz.
  İddia atıldığı için yalnız kapsam eksik kaldıysa (`dropped_coverage`) alıntı yoluna geçilir.
- Pipeline düzeltme çağrısını yalnız bozuk biçimde yapar (`repair_reasons={"draft_shape"}`).
- Kararlarda kesik son cümle, öncekini nitelemiyorsa ("Ancak…", "Aksi hâlde…", "Meğer ki…") kırpılır: parça zaten bir
  alıntıdır. Mevzuattaki sıkı kural değişmedi.
- Gündelik dil sözlüğü (`relevance._EVERYDAY_LEGAL_TERMS`): "işten çıkarmak" → fesih, "ev sahibi" → kiraya veren,
  "maaş" → ücret vb. Yalnız anlam aramasında ve mevzuat sıralamasında kullanılır.

Sonuç: 20 soruda 18-19/20 kaynaklı (koşudan koşuya ±1), ortanca ~22 sn; kullanıcının 7 hukuk sorusu iki turda 14/14
cevaplandı (sabah 2/7). Kira artışı 34 → 12-18 sn, yıllık izin 24 → 9 sn. Kıdem (1475 m. 14) hâlâ ~40 sn ve madde
metni + kısa özetle geliyor: model uzun koşul listesini atlayan iddialar yazıyor, kontrol haklı olarak reddediyor.
