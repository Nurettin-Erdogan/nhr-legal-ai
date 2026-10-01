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
    return ConversationContext(
        project_id=conversation["project_id"],
        turns=history_turns_from_rows(reversed(rows)),
    )
