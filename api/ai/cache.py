"""In-process grounded-answer cache keyed by question, model and source versions."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from threading import Lock
from typing import Any
from uuid import UUID

from api.ai.rag import HistoryTurn, RAGContext
from api.ai.verification import VerifiedAnswer
from api.ai.trust import usable_as_evidence


def normalize_question(question: str) -> str:
    return " ".join(question.casefold().split())


def source_fingerprint(contexts: list[RAGContext]) -> str:
    parts = []
    for context in sorted(contexts, key=lambda item: str(item.chunk_id)):
        content_hash = sha256(context.content.encode("utf-8")).hexdigest()[:16]
        revision = "" if context.revision is None else str(context.revision)
        parts.append(
            f"{context.chunk_id}:{context.source_version or ''}:{revision}:{content_hash}:"
            f"{context.source_type}:{context.reference_line}:{context.source_url}:"
            f"{context.verification}:{context.effective_from}:{context.effective_to}:{context.following_article_title}"
        )
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def history_fingerprint(history: Sequence[HistoryTurn]) -> str:
    """Önceki turlar cevabı etkilediği için önbellek anahtarına girer."""
    if not history:
        return ""
    material = "\n".join(f"{turn.question}\n{turn.answer}" for turn in history)
    return sha256(material.encode("utf-8")).hexdigest()


def answer_cache_key(
    *,
    question: str,
    project_id: UUID | None,
    as_of: date | None,
    model: str,
    fingerprint: str,
    history_key: str = "",
    selected_document_ids: Sequence[UUID] = (),
    user_id: UUID | None = None,
) -> str:
    material = "\n".join(
        (
            "natural-sourced-answer-v3",
            normalize_question(question),
            "" if project_id is None else str(project_id),
            "" if as_of is None else as_of.isoformat(),
            model,
            fingerprint,
            history_key,
            ",".join(sorted(str(value) for value in selected_document_ids)),
            "" if user_id is None else str(user_id),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, maxsize: int = 256) -> None:
        self.maxsize = maxsize
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._data.get(key)
            if payload is not None:
                self._data.move_to_end(key)
            return payload

    def put(self, key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = payload
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


answer_cache = AnswerCache()


def restore_verified_natural_answer(payload: dict, contexts: Sequence[RAGContext]) -> VerifiedAnswer | None:
    """Reuse an already checked answer only against the same current evidence.

    This private in-memory object cannot come from an HTTP payload. No model
    recheck is required for identical text/evidence; missing, changed or no
    longer trusted sources invalidate it. Ordinary cached prose is not proof.
    """
    from dataclasses import replace
    answer = payload.get("_verified_natural_answer")
    if not isinstance(answer, VerifiedAnswer) or not answer.grounded or answer.answer_kind != "legal":
        return None
    available = {c.chunk_id: c for c in contexts if usable_as_evidence(c)}
    if any(c.chunk_id not in available for c in answer.contexts):
        return None
    current = tuple(available[c.chunk_id] for c in answer.contexts)
    if source_fingerprint(list(current)) != source_fingerprint(list(answer.contexts)):
        return None
    return replace(answer, contexts=current)
