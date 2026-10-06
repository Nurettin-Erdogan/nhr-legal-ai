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

Bilinen sınırlar:

- Eşleşme sözcük tabanlıdır; kanun cümlesi sorunun sözcüklerini taşımıyorsa aday olamaz.
- Birincil maddeye kilitlenen soruda madde soruyu doğrudan yanıtlamıyorsa cevap "yeterli bilgi yok" olur
  (ör. "kira artışı için dava açmak şart mı?"); içtihatla tamamlama yapılmaz.
- Cevap süresi 6–55 sn arasındadır (yerel model); uzun maddede özet en uzun adımdır.

Testler: `tests/test_followup_questions.py`, `tests/test_statute_summary.py`, `tests/test_fast_statute.py`,
`tests/test_case_questions.py`.
