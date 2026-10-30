"""Recognise source-free social turns without relaxing legal grounding.

This is deliberately not an LLM intent classifier: every accepted message must
consist entirely of the finite social phrases below. Unknown words, numbers,
links, instructions and ambiguous follow-ups stay on the grounded answer path.
The caller must validate conversation ownership and scope *before* using this
shortcut, just as it does for a substantive question.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.ai.rag import HistoryTurn


_TURKISH_ASCII = str.maketrans("çğıöşü", "cgiosu")
_PUNCTUATION = re.compile(r"[.,!?;:]+")
_SPACES = re.compile(r"\s+")
_ALLOWED_TEXT = re.compile(r"[a-z ]+")

# Address terms belong only to a greeting; they cannot consume arbitrary text.
_ADDRESS = r"(?: (?:jurisai|asistan|arkadasim|dostum))?"
_PHRASES = {
    "greeting": (
        r"(?:merhaba(?:lar)?|selam(?:lar)?|selamun aleykum|selamunaleykum|"
        r"gunaydin|iyi gunler|iyi aksamlar|iyi geceler|hey|hello|hi)" + _ADDRESS
    ),
    "wellbeing": (
        r"nasilsin(?:iz)?|naber|ne haber|ne var ne yok|keyfin nasil|"
        r"keyifler nasil|iyi misin(?:iz)?|napiyorsun|ne yapiyorsun|"
        r"nabiyon|nabiyosun|nabion|nabiosun"
    ),
    "thanks": (
        r"(?:cok )?(?:tesekkurler|tesekkur ederim|tesekkur ediyorum|"
        r"tesekkur ederiz|sag ol(?:un)?|sagol(?:un)?|eyvallah|thanks|thank you)"
    ),
    "goodbye": (
        r"gorusuruz|gorusmek uzere|hosca kal(?:in)?|hoscakal(?:in)?|"
        r"gule gule|kendine iyi bak|kendinize iyi bakin|bye(?: bye)?"
    ),
    "help": (
        r"(?:bana )?(?:nasil yardimci olabilirsin|yardim eder misin|"
        r"yardimci olur musun)|ne yapabilirsin|neler yapabilirsin|"
        r"neler yapabiliyorsun|ne yapabiliyorsun|yardim(?: et)?|"
        r"seni nasil kullanabilirim|nasil kullanabilirim"
    ),
}
_PART = "|".join(f"(?P<{kind}>{phrases})" for kind, phrases in _PHRASES.items())
_SOCIAL_PART = re.compile(rf"(?:{_PART})(?= |$)")
_REPLIES = {
    "greeting": "Merhaba! Nasıl yardımcı olabilirim?",
    "wellbeing": "Merhaba! Buradayım, yardımcı olmaya hazırım. Neye bakalım?",
    "thanks": "Rica ederim! Başka bir konuda da yardımcı olabilirim.",
    "goodbye": "Görüşmek üzere! İhtiyacınız olduğunda buradayım.",
    "help": (
        "Kaynaklarımızdaki mevzuat ve kararları araştırabilir, seçtiğiniz belgeleri "
        "inceleyip özetleyebilirim. Neye bakmamı istersiniz?"
    ),
}

NON_LEGAL_REPLY = (
    "Bu hukuki bir soru değil. Ben hukuki sorularda yardımcı olabilirim; "
    "hukukla ilgili bir sorunuzu yazabilirsiniz."
)

# Match complete, unambiguous requests, not a topic keyword. A pizza order,
# recipe copyright dispute or workplace cooking accident must still reach RAG.
_FOOD = r"(?:pizza|kek|pasta|ekmek|corba|makarna|yemek|kurabiye)"
_REQUEST_END = r"(?:ver|verir misin|verirmisin|verir misiniz|versene|verebilir misin|anlat|nedir|istiyorum|oner)"
_OFF_TOPIC = re.compile(
    rf"(?:(?:merhaba |selam )?(?:bana )?(?:en iyi |kolay |guzel |bir )?{_FOOD} "
    rf"(?:tarifi(?:ni)?(?: {_REQUEST_END})?|nasil yapilir|nasil yapabilirim)"
    r"|(?:bugun |yarin )?hava (?:nasil|nasil olacak)"
    r")(?: lutfen)?"
)


def out_of_scope_reply(question: str) -> str | None:
    """Only explicit nonlegal requests; unknown/ambiguous questions use RAG."""
    text = _normalise_social_text(question)
    return NON_LEGAL_REPLY if text is not None and _OFF_TOPIC.fullmatch(text) else None


def _normalise_social_text(question: str) -> str | None:
    if not question or len(question) > 256:
        return None
    # Do not silently drop bidi controls, zero-width characters or other hidden
    # instructions. Ordinary spacing and Turkish/ASCII spellings are sufficient.
    if any(unicodedata.category(char).startswith("C") and char not in "\t\r\n" for char in question):
        return None
    text = unicodedata.normalize("NFC", question).replace("İ", "i").lower()
    text = text.translate(_TURKISH_ASCII)
    text = _PUNCTUATION.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text if _ALLOWED_TEXT.fullmatch(text) else None


def conversation_reply(question: str, *, history: Sequence[HistoryTurn] = ()) -> str | None:
    """Return a nonlegal social reply, or ``None`` for the grounded pipeline.

    History is accepted to keep the router contract explicit, but is deliberately
    not interpreted. In particular, ``evet``, ``tamam``, ``ne demek`` and similar
    follow-ups must not lose the legal question/scope from the preceding turn.
    A fresh, complete greeting remains a greeting even after a legal discussion.
    """
    text = _normalise_social_text(question)
    if text is None:
        return None

    position = 0
    kinds: set[str] = set()
    parts = 0
    while position < len(text):
        match = _SOCIAL_PART.match(text, position)
        if match is None or parts >= 6:
            return None
        assert match.lastgroup is not None
        kinds.add(match.lastgroup)
        parts += 1
        position = match.end()
        if position < len(text):
            position += 1  # Normalisation has collapsed separators to one space.

    for kind in ("help", "goodbye", "wellbeing", "thanks", "greeting"):
        if kind in kinds:
            return _REPLIES[kind]
    return None
