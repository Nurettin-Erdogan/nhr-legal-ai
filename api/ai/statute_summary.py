"""Uzun kanun maddesi cevabının üstüne konan, soruya odaklı kısa özet.

Cevabın kendisi değişmez: madde metni yine kaynaktan aynen, atıflarıyla gösterilir ve hukuki dayanak odur. Bu modül yalnız okumayı
kolaylaştıran ayrı bir "Kısa özet" kutusu üretir; 6.000 karakterlik İş K. 1475 m. 14 tek blok hâlinde "cevap" diye sunuluyordu
(ölçüldü: 2026-10-05).

Güvence katmanları (özet resmî metin gibi sunulmaz, "yapay zekâ özeti" diye etiketlenir):

* Model yalnız tek bir maddenin metnini görür ve yalnız ondan yazar.
* Her özet maddesi **kodla** denetlenir (`case_summary.bullet_supported`): maddede olmayan sayı/oran/süre, kanun ya da karar
  numarası ve metinle sözcük örtüşmesi zayıf cümle elenir; "X, aksi halde Y" yapısını tersine çeviren cümle elenir.
* Kalanlar bir de **modele denetletilir** (`case_summary.check_bullets`): koşul, olumsuzluk ya da kapsam değişmişse elenir.
* Denetimler yalnız ELER. Hiç madde kalmazsa özet gösterilmez; cevap yine tam madde metnidir.

Özet bir koşulu atlayabilir (eksik olabilir); bu yüzden arayüz her zaman "madde metnini esas alın" der ve tam metin hemen altındadır.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from api import case_summary
from api.ai.verification import VerifiedAnswer

MIN_ANSWER_CHARS = 300  # kısa madde de doğrudan cevapla açıklanır; çok kısa (tek satır) alıntı zaten cevaptır
MAX_SOURCE_CHARS = 7000  # yerel modelin bağlam penceresi (4096 belirteç) için üst sınır
MAX_BULLETS = 5

# Önce sorunun doğrudan cevabı, sonra koşullar: kullanıcı "TÜFE'nin üzerinde zam yapılabilir mi?" diye sordu, cevap madde
# metninin satır satır kopyası ve soruyla ilgisiz fıkraların özeti oldu ("yapay zekâ gibi anlaşılır cevap vermiyor", 2026-10-18).
SYSTEM = (
    "Türk hukuku asistanısın. SORU'yu aşağıdaki KANUN MADDESİ'ne dayanarak, bir avukatın müvekkiline anlatacağı gibi açık ve "
    "sade Türkçeyle cevapla. İlk madde sorunun DOĞRUDAN cevabı olsun; soru evet/hayır sorusuysa 'Evet,' ya da 'Hayır,' diye başla. "
    "Sonraki maddelerde yalnız cevabı etkileyen koşul ve istisnaları yaz; soruyla ilgisiz fıkraları yazma. "
    "YALNIZCA madde metninde yazanları kullan; metinde olmayan süre, oran, koşul, kanun ya da sonuç EKLEME. "
    "Koşulları ve istisnaları değiştirme; kendi yorumunu katma. Her madde tek, KISA bir cümle olsun (en çok 30 sözcük) ve '- ' ile "
    "başlasın; en çok 4 madde. "
    "Madde metni soruyu cevaplamıyorsa yalnız '- Madde bu soruyu doğrudan düzenlemiyor.' yaz. Başlık ya da giriş yazma."
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


_AMOUNT_QUESTION = re.compile(r"ne kadar|kaç |hangi süre|oranı ne|yüzde kaç")
_HAS_AMOUNT = re.compile(r"\d|yüzde|on dört|yirmi|otuz|kırk|elli|altmış|doksan|iki |üç |dört |beş |altı |sekiz ")
_YES_NO = re.compile(r"^\s*(evet|hayır)\s*[,.:;]\s*", re.IGNORECASE)
_NEGATIVE = re.compile(r"\b\w+(?:amaz|emez|maz|mez|amıyor|emiyor)\b|\bdeğil|\byasak|\bolanaksız|\bmümkün değil", re.IGNORECASE)


def coherent_polarity(bullet: str) -> str:
    """Baştaki "Evet,"/"Hayır," cümlenin hükmüyle çelişiyorsa o sözcük atılır; hüküm cümlesi aynen kalır.

    Yerel model "TÜFE'nin üzerinde zam yapabilir mi?" sorusuna "Evet, ev sahibi TÜFE'nin üzerinde zam yapamaz" yazdı
    (2026-10-18). Hangisinin doğru olduğunu kod bilemez; çelişkili kısa cevabı göstermemek yeter.
    """
    match = _YES_NO.match(bullet)
    if not match:
        return bullet
    rest = bullet[match.end():].strip()
    negative = bool(_NEGATIVE.search(rest.replace("İ", "i").lower()))
    if (match.group(1).lower() == "evet") == negative and rest:
        first = {"i": "İ", "ı": "I"}.get(rest[0], rest[0].upper())  # Türkçe büyük harf: işveren -> İşveren
        return first + rest[1:]
    return bullet


def checked_text(bullet: str, question: str, source: str) -> str:
    """Denetlenecek metin: sorudaki yıl ("2026 yılında") maddeyi düşürmez; kaynakta olmayan başka her sayı yine düşürür.

    Model soruyu çerçeve olarak tekrar edince ("2026 yılında kira bedeli …") doğru cümle "kaynakta olmayan sayı" diye eleniyordu
    (2026-10-18). Yıl kullanıcının sorusundan gelir, kaynak hakkında bir iddia değildir.
    """
    years = {year for year in _YEAR.findall(question) if year not in source}
    return _YEAR.sub(lambda match: "" if match.group() in years else match.group(), bullet) if years else bullet

_MARKER = re.compile(r"\s*\[\s*K\s*\d+\s*\]", re.IGNORECASE)
_NO_ANSWER = re.compile(r"doğrudan düzenlemiyor|cevaplamıyor|yer almıyor", re.IGNORECASE)

Generate = Callable[[str, str], Awaitable[str]]


def eligible(answer: VerifiedAnswer) -> bool:
    """Yalnız tek bir resmî kanun maddesine dayanan, kaynağa bağlı ve uzun cevaplar özetlenir."""
    if not answer.grounded or len(answer.text) < MIN_ANSWER_CHARS or not answer.contexts:
        return False
    if any(context.source_type != "legislation" or context.verification != "official" for context in answer.contexts):
        return False
    return len({(context.law_no, context.article_no) for context in answer.contexts}) == 1


def article_text(answer: VerifiedAnswer) -> str:
    """Cevapta gösterilen madde metni (atıf işaretleri olmadan). Özet yalnız kullanıcının gördüğü metne dayanır."""
    return _MARKER.sub("", answer.text).strip()


def complete_lines(partial: str) -> str:
    """Kesilmiş çıktının tamamlanmış satırları: son satır yarım kalmış olabileceğinden her zaman atılır."""
    lines = [line for line in partial.splitlines() if line.strip()]
    return "\n".join(lines[:-1])


async def build(question: str, answer: VerifiedAnswer, generate: Generate) -> tuple[str, ...]:
    """Denetimden geçen özet maddeleri; uygun değilse ya da hiçbiri geçmezse boş."""
    if not eligible(answer):
        return ()
    source = article_text(answer)
    if len(source) > MAX_SOURCE_CHARS:
        return ()  # madde bağlam penceresine sığmıyor: yarım metinden özet çıkarılmaz
    context = answer.contexts[0]
    title = f"{context.law_name or ''} m. {context.article_no or ''}".strip()
    prompt = f'SORU: {question.strip()}\n\nKANUN MADDESİ ({title}):\n"""\n{source}\n"""\n\nMaddeler:'
    try:
        raw = await generate(SYSTEM, prompt)
    except Exception as exc:  # noqa: BLE001 - özet isteğe bağlıdır; üretilemezse cevap özetsiz gösterilir
        # Model "en çok 5 madde" sınırını aşıp uzun bir maddeyi baştan sona saymaya kalkınca çıktı sınırda kesiliyor ve özet hiç
        # çıkmıyordu (ölçüldü: 2026-10-06, İş K. 1475 m. 14). Maddeler birbirinden bağımsızdır: kesilen son satır atılır,
        # tamamlanmış satırlar aynı denetimlerden geçirilir.
        raw = complete_lines(getattr(exc, "partial", "") or "")
        if not raw:
            return ()
    bullets = [coherent_polarity(bullet) for bullet in case_summary.parse_bullets(raw) if not _NO_ANSWER.search(bullet)]
    bullets = [bullet for bullet in dict.fromkeys(bullets)
               if case_summary.bullet_supported(checked_text(bullet, question, source), source)][:MAX_BULLETS]
    if not bullets:
        return ()
    windows, _coverage = case_summary.split_windows(source, size=case_summary.WINDOW_CHARS, limit=4)
    try:
        # Denetçi soruyu da görür: kaynağa uygun ama soruyu cevaplamayan madde (kıdem süresi sorusuna "askerlikte tazminat")
        # kısa cevap diye gösterilmez; hiçbiri kalmazsa cevap eskisi gibi madde metnidir (2026-10-18).
        kept, _rejected = await case_summary.check_bullets(bullets, windows, generate, instruction=f"SORU: {question.strip()}")
    except Exception:  # noqa: BLE001
        return ()
    # Süre/miktar soran soruya süresiz "cevap" gösterilmez (kıdem için "ne kadar çalışmak gerekir?" sorusuna yalnız askerlik
    # istisnası kaldı, 2026-10-18): o zaman cevap eskisi gibi madde metnidir.
    from api.ai.passages import contains_duration, is_duration_question
    asks_amount = is_duration_question(question) or bool(_AMOUNT_QUESTION.search(question.lower()))
    if kept and asks_amount and not any(contains_duration(bullet) or _HAS_AMOUNT.search(bullet.lower()) for bullet in kept):
        return ()
    return tuple(kept)
