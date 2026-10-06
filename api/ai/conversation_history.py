"""Çok turlu sohbet: önceki turları prompta ve aramaya taşır.

Geçmiş yalnız soruyu anlamak içindir, kaynak değildir. Bu yüzden önceki cevaplardaki
`[K1]` gibi atıf işaretleri temizlenir: yeni cevabın işaretleri yalnız bu turda getirilen
kaynaklara karşılık gelmelidir.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

from api.ai.rag import HistoryTurn
from api.ai.retrieval import distinctive_question_words

# Yerel modelin bağlamı dar (num_ctx 3072); iki tur ~450 token tutar.
MAX_HISTORY_TURNS = 2
_QUESTION_CLIP = 300
_ANSWER_CLIP = 350
_FETCH_ROWS = 12

_MARKER_RE = re.compile(r"\s*\[\s*K\s*\d+\s*\]", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")

# Tek başına arama yapılamayan devam soruları ("Peki bunun süresi ne kadar?").
_REFERENTIAL_WORDS = frozenset(
    {
        "peki", "ayrıca", "şimdi", "bunun", "bunlar", "bunları", "buna", "bunu",
        "şunun", "onun", "onlar", "aynı", "yukarıdaki",
    }
)

_REFERENTIAL_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(sorted(_REFERENTIAL_WORDS, key=len, reverse=True)) + r")(?!\w)",
    re.IGNORECASE,
)

_CONVERSATION_SQL = """
SELECT id, project_id
FROM conversations
WHERE id = %s AND deleted_at IS NULL
"""

_MESSAGES_SQL = """
SELECT role, content, metadata
FROM messages
WHERE conversation_id = %s
  AND deleted_at IS NULL
  AND role IN ('user', 'assistant')
ORDER BY created_at DESC, id DESC
LIMIT %s
"""


class ConversationNotFound(LookupError):
    """Sohbet yok ya da RLS bu kullanıcıya göstermiyor."""


@dataclass(frozen=True, slots=True)
class ConversationContext:
    project_id: UUID | None
    turns: tuple[HistoryTurn, ...]
    # Son kullanıcı soruları (eskiden yeniye), cevabı kaynağa dayanmayanlar DAHİL: takip sorusunun konusu
    # "yeterli kaynak yok" denen bir önceki sorudan da gelebilir. Cevap metni buraya girmez.
    questions: tuple[str, ...] = ()


def _clip(text: str, limit: int) -> str:
    compact = _SPACE_RE.sub(" ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def strip_markers(text: str) -> str:
    return _SPACE_RE.sub(" ", _MARKER_RE.sub("", text)).strip()


def history_turns_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    max_turns: int = MAX_HISTORY_TURNS,
) -> tuple[HistoryTurn, ...]:
    """Eskiden yeniye sıralı satırlardan (soru, cevap) çiftleri çıkarır.

    Kaynağa dayanmayan cevaplar (`grounded=false`) modele geri verilmez: "kaynak
    yetersiz" gibi bir cevabı bağlam yapmak sonraki turu da o yöne çeker.
    """
    turns: list[HistoryTurn] = []
    pending_question: str | None = None
    for row in rows:
        role = row["role"]
        if role == "user":
            pending_question = str(row["content"])
        elif role == "assistant" and pending_question is not None:
            metadata = row.get("metadata") or {}
            answer = strip_markers(str(row["content"]))
            if metadata.get("grounded") is not False and answer:
                turns.append(
                    HistoryTurn(
                        question=_clip(pending_question, _QUESTION_CLIP),
                        answer=_clip(answer, _ANSWER_CLIP),
                    )
                )
            pending_question = None
    return tuple(turns[-max_turns:]) if max_turns > 0 else ()


MAX_PRIOR_QUESTIONS = 3

REWRITE_INSTRUCTION = """Türkçe hukuk sohbetinde bir takip sorusunu tek başına anlaşılır hâle getirirsin.
ÖNCEKİ SORULAR yalnız konuyu anlamak içindir. YENİ SORU'daki "bu, bunun, o, peki, aynı" gibi göndermeleri
ya da eksik bırakılan konuyu önceki sorulardaki konuyla tamamla.
YENİ SORU zaten tek başına anlaşılıyorsa ya da konu değişmişse onu AYNEN geri ver.
Sonuç TEK bir soru cümlesi olsun; önceki soruyu olduğu gibi başına ekleme.
Soruyu cevaplama. Bilgi, süre, sayı, madde veya kanun adı EKLEME; yalnız önceki sorularda geçen sözcükleri kullan.
Örnek: önceki "İhbar tazminatı nedir?", yeni "Peki bunun zamanaşımı süresi kaç yıl?" -> "İhbar tazminatının zamanaşımı süresi kaç yıl?"
Örnek: önceki "İşçi hangi hallerde kıdem tazminatına hak kazanır?", yeni "Peki nasıl hesaplanır?" -> "Kıdem tazminatı nasıl hesaplanır?"
Örnek: önceki "İhbar tazminatı nedir?", yeni "Kira artış oranı nasıl belirlenir?" -> "Kira artış oranı nasıl belirlenir?"
Yalnız JSON döndür: {"question":"..."}"""

# Yeniden yazımda serbestçe eklenebilecek, konu taşımayan sözcükler (kök olarak karşılaştırılır).
_REWRITE_FREE_WORDS = frozenset(
    "için icin olan olarak ilişkin iliskin hakkında konusunda nedir nelerdir nasıl nasil hangi kadar kimdir "
    "halinde durumunda bakımından açısından yönünden gereken gerekir olmalı olmalıdır olur olabilir "
    "edilir yapılır yapilir sayılır varsa yoksa ayrıca göre gore ilgili midir mıdır mudur müdür değil".split()
)


def _stem(word: str) -> str:
    return word[: max(4, len(word) - 3)]


# Yeniden yazıma, önceki sorularda geçmediği hâlde girebilecek tek sözcük kısa bir ek sözcüktür. Uzun sözcükler ve aşağıdaki
# kısa hukuk terimleri anlam taşır; önceki sorularda yoksa model onları uydurmuştur.
_MAX_FOREIGN_WORD_CHARS = 7
_FOREIGN_LEGAL_STEMS = frozenset(_stem(word) for word in (
    "dava", "davası", "süre", "süresi", "faiz", "ceza", "cezası", "fesih", "feshi", "itiraz", "temyiz", "istinaf",
    "madde", "kanun", "hakkı", "borç", "borcu", "alacak", "icra", "tahliye", "nafaka", "velayet", "kira", "tazmin",
    "iptal", "iptali", "karar", "kararı", "sözleşme", "ihtar", "ihbar", "kıdem", "haciz", "tespit", "tebliğ",
))


def _content_words(text: str) -> list[str]:
    return [word for word in _WORD_RE_LOCAL.findall(text.casefold().replace("i̇", "i")) if len(word) >= 4]


_WORD_RE_LOCAL = re.compile(r"[0-9a-zçğıöşüâîû]+")


def prior_questions_from_rows(rows: Iterable[Mapping[str, Any]], *, limit: int = MAX_PRIOR_QUESTIONS) -> tuple[str, ...]:
    """Eskiden yeniye sıralı satırlardan son kullanıcı sorularını çıkarır (cevabın durumundan bağımsız)."""
    questions = [_clip(str(row["content"]), _QUESTION_CLIP) for row in rows if row["role"] == "user"]
    return tuple(questions[-limit:]) if limit > 0 else ()


def accept_rewrite(candidate: object, question: str, prior_questions: tuple[str, ...]) -> str | None:
    """Modelin önerdiği tek başına soruyu kodla denetler; güvenli değilse None (çağıran eski yola döner).

    Kurallar: (1) kullanıcının yazdığı içerik sözcüklerinin hiçbiri düşmemeli, (2) eklenen her içerik sözcüğü önceki
    SORULARDA geçmeli (model konu, süre ya da kanun uyduramaz), (3) sayı eklenemez, (4) gerçekten bir şey eklenmiş olmalı.
    Bu metin yalnız aramayı ve kanıt seçimini yönlendirir; hukuki iddia değildir ve cevaba girmez.
    """
    if not isinstance(candidate, str):
        return None
    rewritten = _SPACE_RE.sub(" ", candidate).strip()
    if not 8 <= len(rewritten) <= 300 or "[" in rewritten or "<" in rewritten:
        return None
    if rewritten.count("?") > 1:
        # İki ayrı soru: model eski soruyu olduğu gibi başa eklemiş. Konu değiştiyse bu, eski konuyu aramaya taşır.
        return None
    lowered = rewritten.casefold()
    for prior in prior_questions:
        core = prior.strip(" ?.!").casefold()
        if len(core) >= 8 and core in lowered and not lowered.startswith(core + " ve "):
            # Eski soru aynen içeride ama yeni soruya "ve" ile bağlanmamış: yeniden yazım değil, yapıştırma.
            # ("<eski soru> ve <yeni soru>" biçimi kabul edilir: model iki soruyu bağlı görmüştür ve yeni sorunun
            # sözcükleri eksiksiz durur; küçük model bağımlı soruları çoğunlukla böyle tamamlıyor.)
            return None
    own = _content_words(question)
    new = _content_words(rewritten)
    new_blob = " ".join(new)
    # "için", "nasıl" gibi konu taşımayan sözcüklerin yeniden yazımda kalması beklenmez ("bunun için dava açmak şart mı?"
    # → "kira artış oranı belirlenirken dava açmak şart mı?" reddediliyordu; ölçüldü: 2026-10-06).
    kept = [word for word in own if word not in _REFERENTIAL_WORDS and word not in _REWRITE_FREE_WORDS]
    if any(_stem(word) not in new_blob for word in kept):
        return None
    own_blob = " ".join(own)
    prior_blob = " ".join(word for prior in prior_questions for word in _content_words(prior))
    added = [word for word in new if _stem(word) not in own_blob]
    topical = []
    foreign = 0
    for word in added:
        if word in _REWRITE_FREE_WORDS or word in _REFERENTIAL_WORDS:
            continue
        if word.isdigit():
            return None
        if _stem(word) in prior_blob:
            topical.append(word)
        elif len(word) > _MAX_FOREIGN_WORD_CHARS or _stem(word) in _FOREIGN_LEGAL_STEMS:
            # Önceki sorularda geçmeyen bir hukuk terimi sorunun anlamını değiştirir ve kullanıcıya "şöyle anlaşıldı"
            # diye gösterilir: "Bu süre ne zaman başlar?" → "… davasının zamanaşımı süresi …" (süre hak düşürücü olabilir).
            return None
        else:
            foreign += 1  # çekim/bağlaç gibi konu taşımayan kısa ek sözcük olabilir ("olduğu", "geçerli")
    if not topical:
        return None  # hiçbir konu eklenmedi: soru zaten bağımsız ya da model aynen geri verdi
    if foreign > 1:
        return None  # önceki sorularda olmayan birden çok sözcük: model konu uyduruyor olabilir
    if set(re.findall(r"\d+", rewritten)) - set(re.findall(r"\d+", question)) - set(re.findall(r"\d+", " ".join(prior_questions))):
        return None
    return rewritten


def standalone_question(provider: Any, question: str, prior_questions: tuple[str, ...]) -> str | None:
    """Takip sorusunu önceki sorulara göre tek başına anlaşılır hâle getirir; emin olunamazsa None.

    "İhbar tazminatı nedir?" → "Peki bunun zamanaşımı süresi kaç yıl?" sorusunda arama ve kanıt seçimi yalnız
    "zamanaşımı süresi" ile yapılıyor, haksız fiil zamanaşımını anlatan ilgisiz bir karar cevap oluyordu (ölçüldü: 2026-10-05).
    """
    if not prior_questions:
        return None
    import json

    prompt = json.dumps(
        {"önceki_sorular": list(prior_questions[-MAX_PRIOR_QUESTIONS:]), "yeni_soru": question}, ensure_ascii=False
    )
    try:
        raw = provider.generate(system_instruction=REWRITE_INSTRUCTION, prompt=prompt).strip()
        if raw.startswith("```json") and raw.endswith("```"):
            raw = raw[7:-3].strip()
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - sağlayıcı hatası ya da bozuk çıktı: eski sezgisel yola dönülür
        return None
    return accept_rewrite(data.get("question") if isinstance(data, dict) else None, question, prior_questions)


def retrieval_question(question: str, history: tuple[HistoryTurn, ...]) -> str:
    """Devam sorusu kendi başına aranamıyorsa önceki sorunun konusunu ekler.

    Arama sorudaki ilk iki içerik kelimesini kullanır; bu yüzden önceki soru tümüyle
    başa eklenmez (yeni terim kaybolurdu). Yalnız onun ilk ayırt edici kelimesi konu
    olarak öne konur, sorunun kendisi (madde/kanun numaraları dahil) korunur.
    """
    if not history:
        return question
    words = distinctive_question_words(question)
    fillers = [word for word in words if word in _REFERENTIAL_WORDS]
    content = [word for word in words if word not in _REFERENTIAL_WORDS]
    if not fillers and len(content) >= 2:
        return question
    previous = history[-1].question
    cleaned = _SPACE_RE.sub(" ", _REFERENTIAL_RE.sub(" ", question)).strip()
    topic = distinctive_question_words(previous)
    if not content or not topic:
        return f"{previous} {cleaned}".strip()
    return f"{topic[0]} {cleaned}"


def load_conversation_context(
    connection: psycopg.Connection,
    conversation_id: UUID,
) -> ConversationContext:
    """Sohbeti RLS altında okur; erişilemiyorsa `ConversationNotFound` fırlatır."""
    conversation = connection.execute(_CONVERSATION_SQL, (conversation_id,)).fetchone()
    if conversation is None:
        raise ConversationNotFound(str(conversation_id))
    rows = connection.execute(_MESSAGES_SQL, (conversation_id, _FETCH_ROWS)).fetchall()
    ordered = list(reversed(rows))
    return ConversationContext(
        project_id=conversation["project_id"],
        turns=history_turns_from_rows(ordered),
        questions=prior_questions_from_rows(ordered),
    )
