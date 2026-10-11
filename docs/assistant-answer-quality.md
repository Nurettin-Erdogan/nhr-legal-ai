# Asistan cevabının kalitesi: takip soruları, madde özeti, konu maddeleri

Genel sohbet (`/dashboard/ai`) ve dava sohbeti aynı hattı kullanır (`api/ai/pipeline.py`). Bu belge, cevabın
kaynağa bağlılığını bozmadan kaliteyi artıran ek adımları ve her birinin **kod tarafındaki denetimini** anlatır.
Dava belgelerine özgü kurallar: [office-document-rag.md](office-document-rag.md). Ölçümler yerel modelle
(`qwen3.5:4b`) alınmıştır; başka modelde yeniden ölçülmelidir.

## 1. Takip sorusu ("Peki bunun süresi kaç yıl?")

`api/ai/conversation_history.py`

- Model, yeni soruyu önceki **sorulara** bakarak tek başına anlaşılır hâle getirmeyi önerir (`standalone_question`).
  Önceki cevaplar modele verilmez; yalnız sorular.
- Öneri kodla denetlenir (`accept_rewrite`), geçemezse yok sayılır ve eski yola dönülür:
  - kullanıcının yazdığı konu sözcükleri düşmemiş olmalı ("için", "nasıl" gibi dolgu sözcükleri hariç);
  - eklenen her konu sözcüğü önceki sorularda geçmeli; önceki sorularda olmayan bir hukuk terimi
    ("zamanaşımı", "hak düşürücü", "faiz"…) eklenemez, sayı eklenemez;
  - iki ayrı soru cümlesi (eski sorunun yapıştırılması) reddedilir; "<eski soru> ve <yeni soru>" biçimi kabul edilir.
- Kabul edilen metin aramayı ve kanıt seçimini yönlendirir, cevaba girmez. Arayüz onu cevabın üstünde
  "Önceki sorunuza göre şöyle anlaşıldı: …" diye gösterir; kullanıcı yanlış yorumu görür.

## 2. Konuya uyan resmî madde (genel sohbet ve dava sohbeti)

`api/statute_hints.py` (konu → kanun/madde tablosu), `pipeline._case_statute_contexts`

- Soru tablodaki bir konuyla eşleşirse ilgili madde korpustan okunur ve adayların **başına** eklenir. Madde resmî
  doğrulanmış ve güncel olmalı, metni tablodaki beklenen ifadeyi taşımalıdır; değilse eklenmez. Metin üretilmez.
- Neden: sözcük araması "tüketici ayıplı malda hangi haklara sahiptir" sorusuna yalnız karar, "işe iade davası açma
  süresi" sorusuna yalnız 2015–2016 kararlarını getiriyordu. Madde yalnız adaydır; cümle alaka süzgecinden geçmezse
  cevaba girmez.
- Tarihli sorularda (`as_of`) eklenmez. Tablo `scripts/verify_statute_hints.py` ile korpusa karşı denetlenir.
- **Birincil madde niyetleri** (`relevance.question_intent`) ayrıdır: soru bir maddeye kilitlenir ve cevap yalnız o
  maddeden kurulur. 2026-10-06'da eklenen: işe iade + süre → İş Kanunu m. 20 (usul 2017'de değişti; eski kararlar
  önceki usulü anlatır).

### 2026-10-08: konu maddesinin cümlesi soru sözcüklerini taşımak zorunda değil

`authority.topic_statute_terms`, `evidence_selection.evidence_candidates`, `verification.verify_answer`

- **Sorun (ölçüldü):** "İş sözleşmesinin haksız feshinde işçi hangi tazminatları talep edebilir?" ve "İşe iade
  davasının koşulları nelerdir?" sorularında doğru madde aday olarak geliyor ama cevap yalnız kararlara dayanıyordu.
  Kanun cümlesi ("Bildirim şartına uymayan taraf … tazminat ödemek zorundadır") sorunun sözcüklerini taşımadığı için
  hem aday süzgecinde hem cevap denetiminde "alakasız" sayılıyordu.
- **Kural:** Sorunun konusu tablodaysa ve kaynak o konunun **resmî doğrulanmış** maddesiyse, maddenin konu sözcüğünü
  (`Hint.expect`) taşıyan cümle alakalıdır. Aynı kural aday seçiminde ve cevap denetiminde kullanılır. Maddenin başka
  konudaki fıkrası, tablodaki madde olmayan kaynak ve doğrulanmamış metin bu kuraldan yararlanmaz; içtihat isteyen
  soruda ("Yargıtay kararları…") uygulanmaz. Cümle yine kaynaktan aynen alınır ve kaynak-destek denetiminden geçer.
- **Sunum:** Konu maddesinin cümleleri listenin başında ve **maddedeki sırasıyla** verilir (kural önce, ayrıntı sonra),
  kaynak başına payı 1,5 katıdır, toplam bütçenin en çok %55'ini alır (kararlar da aday kalır). Seçim isteminde bu
  cümleler "sorunun konusunu düzenleyen kanun maddesi" diye etiketlenir; talimata "kuralı koyan madde cümlesi varsa
  önce onu seç" satırı eklendi.
- **Kanunu adıyla anan açık madde sorusu** (`retrieval.named_law_numbers`): "Anayasanın 36. maddesi", "TBK m. 344",
  "İİK m. 67" artık açık madde sorusudur; üç haneli madde numarası kanun numarası sanılmaz. Açık yazılmış kanun
  numarası her zaman adı ezer ("1475 sayılı İş Kanunu m. 14"). Belirsiz kısaltma (TMK) eşlenmez.
- **Yeni konular:** geçersiz feshin sonuçları (4857/21), haksız fesih tazminatları (4857/17, 1475/14), eşit davranma
  (4857/5), iş uyuşmazlığında arabuluculuk (7036/3), idari istinaf/temyiz (2577/45, 46), KDK başvurusu (6328/17),
  bireysel başvuru (Anayasa m. 148), adil yargılanma (Anayasa m. 36). Tablo 60 ipucuyla korpusa karşı doğrulandı.
- **Karar araması zaman aşımına uğrarsa:** ikinci denemede de düşerse ve konunun maddesi okunabildiyse cevap o
  maddeden verilir, arama "kısmi" diye bildirilir (`decision_search: timeout`). Yoğun diskte aynı soru art arda dört
  kez zaman aşımına uğradı (ölçüldü); eskiden kullanıcı "Hukuk kaynakları aranamadı" hatası alıyordu. Tabloda konusu
  olmayan soruda davranış değişmedi.

### 2026-10-10: asıl kural cümlesi güvencesi

`statute_hints.Hint.anchor`, `evidence_selection.include_rule_sentences`, `scripts/verify_statute_hints.py`

- **Sorun (ölçüldü):** Model konu maddesinden cümle seçiyor ama maddenin asıl kuralını atlayabiliyor: "haksız fesihte hangi
  tazminatlar" sorusunda İş Kanunu m. 17'den bildirim sürelerini seçip ihbar tazminatı cümlesini, KDK sorusunda m. 17'nin
  "idari başvuru yolları tüketilmeli" fıkrasını almıyordu. Bu karta sığan daha büyük yerel modeller de aynı cümleyi kaçırıyor
  ve düşünme modu kullanılamıyor (`docs/local-model-comparison.md`); yani çözüm modelde değil.
- **Kural:** Konu tablosundaki ipucu, maddenin o konudaki asıl kural cümlesinin ayırt edici bir parçasını taşıyabilir
  (`anchor`; 17 ipucunda var). Model **o maddeden** bir cümle seçmiş ama bu cümleyi almamışsa, cümle aday listesinden aynen ve
  kendi [K] işaretiyle alınıp o maddeye atıf yapan ilk satırın önüne konur. Metin üretilmez; eklenen satır da kaynak-destek
  denetiminden geçer.
- **Sınırlar bilerek dar:** Model o maddeden hiç cümle seçmediyse eklenmez (soru konuya değip maddeyi ilgilendirmeyebilir:
  "ihbar tazminatında zamanaşımı"). Cümle aday listesinde yoksa, madde resmî doğrulanmış değilse, soru içtihat istiyorsa ya da
  açık madde sorusuysa (madde zaten bütün kurulur) eklenmez.
- **Doğrulama:** Her çapa korpustaki resmî madde metninde **aynen ve tek yerde** geçmelidir; `verify_statute_hints.py` bunu
  denetler (17/17; "kıdem tazminatı ödenir" iki yerde geçtiği için daha uzun parçayla değiştirildi).
- **Ölçüm:** 15 etiketli soruda uygulamanın gerçek cevap üretimiyle (aynı kaynaklar, adım kapalı/açık): etiket cümlesi
  16/18 → 18/18, tam soru 13/15 → 15/15, doğrulaması geçmeyen cevap 0 → 0; yalnız iki cevaba birer satır eklendi. **Uyarı:**
  etiketler ile çapalar aynı cümlelerdir (ikisini de ben yazdım); bu sayı modelin değil tablonun kapsamını gösterir. Tabloda
  çapası olmayan konularda davranış değişmedi.

## 3. Uzun madde cevabında "Kısa özet"

`api/ai/statute_summary.py`

- Cevap tek bir resmî kanun maddesine dayanıyor ve uzunsa, üstüne en çok beş maddelik özet eklenir.
- Her özet maddesi önce kodla (sayılar, kanun atıfları, sözcük örtüşmesi), sonra ikinci bir model geçişiyle
  ("denetçi") madde metnine karşı denetlenir; geçemeyen madde gösterilmez. Hiçbiri geçmezse özet yoktur.
- Cevap metni ve atıflar özetten bağımsızdır; özet `grounded` hesabına girmez ve "yapay zekâ özetidir" notuyla gösterilir.
- Özet ek bir model çağrısıdır (ölçülen: 25–50 sn). Doğrulanmış cevap, özet beklenmeden **önizleme** olarak
  gönderilir (`summarizing` olayı, `preview` alanı); arayüz cevabı hemen gösterir, özet gelince ekler.

## 4. Açıklama adımında yokluk/kesinlik denetimi

`api/ai/explanation.py`

Açıklama adımı doğrulanmış alıntıları sade Türkçeyle yeniden söyler; her iddia model denetçisinden geçer. Model
denetçisi, "en az otuz gün" diyen maddeden üretilen "olaya özgü istisnalar söz konusu değildir" cümlesini onayladı.
Bu yüzden kod tarafında ek kural vardır (`unsupported_absolute`): iddiada geçen yokluk/kesinlik ifadesi ("istisna",
"hiçbir", "her durumda", "gerekmez", "yoktur"…) dayandığı alıntıda geçmiyorsa iddia atılır. Kalan iddialar bütün
alıntıları kapsamıyorsa açıklama tümüyle düşer ve kaynak cümleler olduğu gibi gösterilir.

## 5. Denetimden geçmeyen tek satır

Taslak yalnız kaynaktan aynen alınmış cümlelerden oluşur. Bir satır denetimden geçmezse o satır çıkarılır ve kalan
metin baştan doğrulanır (`verification.prune_rejected_lines`); eskiden cevabın tamamı reddediliyordu.

## 6. Eski karar uyarısı

Cevap yalnız kararlara dayanıyor ve en yenisi 8 yıldan eskiyse cevabın başına tarih uyarısı konur
(`explanation.stale_decisions_notice`). Sistem hangi kuralın güncel olduğuna karar vermez; tarihi gösterir.

## Ölçüm

`.local/asst_eval.py` (10 tek soru + 4 takip zinciri, 18 cevap) ile, canlı korpusta:

| Tarih | Kaynaklı cevap | Not |
| --- | --- | --- |
| 2026-10-05 (başlangıç) | — | takip zincirlerinin 1/4'ü konuda kaldı |
| 2026-10-06 | 18 / 18 (ortalama 19 sn, en uzun 59 sn) | 4/4 zincir konuda; işe iade süresi ve ayıplı mal soruları kanun maddesinden |

Sabit 20 soruluk set (`api/ai/eval_questions.py`, `scripts/eval_live_answers.py`), canlı korpusta:

| Tarih | Kaynaklı cevap | Beklenen kanuna atıf | Süre | Not |
| --- | --- | --- | --- | --- |
| 2026-10-07 | 18 / 18 (2 soru ölçüm hatası) | 11 / 18 | ortanca 19 sn, en uzun 54 sn | |
| 2026-10-08 | 20 / 20 | 19 / 20 | ortanca 16 sn, en uzun 59 sn | doğrulanmamış kaynağa atıf oranı 0 |
| 2026-10-08, arama düzeltmesinden sonra | 20 / 20 | 19 / 20 | ortanca 12 sn, en uzun 24 sn | aynı sorular aynı gün ikinci kez soruldu: disk daha sıcaktı, kazancın bir kısmı bundandır |
| 2026-10-10, veri tarafı yükü altında | 20 / 20 | 19 / 20 | ortanca 24 sn, en uzun 46 sn | embedding işçisinin sayım taramaları diski dolduruyordu (`docs/legal-search-performance.md`) |
| 2026-10-10, bakım sonrası, son kod | 20 / 20 | 19 / 20 | ortanca 17 sn, en uzun 35 sn | önbellek soğuk; asıl kural cümlesi güvencesi ve arama sigortası canlıda |

Arama düzeltmesi: resmî katmana üst sınır ve tam sıralı aramaya kısa ilk süre (`docs/legal-search-performance.md`).

- "Beklenen kanuna atıf" sütununda kıdem sorusunun beklentisi düzeltilmiş hâliyle sayıldı: kıdem tazminatını 1475
  sayılı Kanun m. 14 düzenler (4857 m. 120 yalnız o maddeyi yürürlükte bırakır; korpustaki resmî metinden doğrulandı).
- Tek eksik: bireysel başvuru sorusu. **6216 sayılı Kanun korpusta yok** (veri eksiği); cevap Anayasa m. 148'e ve AYM
  kararlarına dayanıyor.
- Bu ölçüm cevabın hukuken doğru ya da eksiksiz olduğunu söylemez; yalnız kaynağa dayandığını ve hangi kaynağa atıf
  yapıldığını ölçer.

Bilinen sınırlar:

- Eşleşme sözcük tabanlıdır; kanun cümlesi sorunun sözcüklerini taşımıyorsa aday olamaz. İstisna: konusu tabloda
  olan sorularda konunun maddesi (bkz. 2, "2026-10-08"). Tabloda olmayan konular için sınır sürer.
- Madde içinde hangi fıkranın seçileceğine model karar verir; yerel model her zaman en uygun cümleyi seçmiyor
  (haksız fesih sorusunda m. 17'den bildirim sürelerini seçti, ihbar tazminatı cümlesini seçmedi; ölçüldü: 2026-10-08).
- Birincil maddeye kilitlenen soruda madde soruyu doğrudan yanıtlamıyorsa cevap "yeterli bilgi yok" olur
  (ör. "kira artışı için dava açmak şart mı?"); içtihatla tamamlama yapılmaz.
- Cevap süresi 6–55 sn arasındadır (yerel model); uzun maddede özet en uzun adımdır.

Testler: `tests/test_followup_questions.py`, `tests/test_statute_summary.py`, `tests/test_fast_statute.py`,
`tests/test_case_questions.py`, `tests/test_topic_statute_evidence.py`, `tests/test_named_law_reference.py`.
