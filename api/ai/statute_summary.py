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

MIN_ANSWER_CHARS = 1400  # bundan kısa cevap zaten okunur; özet gereksizdir (arayüzün daraltma eşiğiyle aynı)
MAX_SOURCE_CHARS = 7000  # yerel modelin bağlam penceresi (4096 belirteç) için üst sınır
MAX_BULLETS = 5

SYSTEM = (
    "Türk hukuku asistanısın. Aşağıdaki KANUN MADDESİ metnine dayanarak SORU'yu kısa maddelerle cevapla. "
    "YALNIZCA madde metninde yazanları kullan; metinde olmayan süre, oran, koşul, kanun ya da sonuç EKLEME. "
    "Koşulları ve istisnaları değiştirme; kendi yorumunu katma. Her madde tek, KISA bir cümle olsun (en çok 30 sözcük) ve '- ' ile "
    "başlasın; en çok 5 madde. Uzun sayımları aynen kopyalama, kısaca özetle. "
    "Madde metni soruyu cevaplamıyorsa yalnız '- Madde bu soruyu doğrudan düzenlemiyor.' yaz. Başlık ya da giriş yazma."
)

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
    bullets = [bullet for bullet in case_summary.parse_bullets(raw) if not _NO_ANSWER.search(bullet)]
    bullets = [bullet for bullet in dict.fromkeys(bullets) if case_summary.bullet_supported(bullet, source)][:MAX_BULLETS]
    if not bullets:
        return ()
    windows, _coverage = case_summary.split_windows(source, size=case_summary.WINDOW_CHARS, limit=4)
    try:
        kept, _rejected = await case_summary.check_bullets(bullets, windows, generate)
    except Exception:  # noqa: BLE001
        return ()
    return tuple(kept)
