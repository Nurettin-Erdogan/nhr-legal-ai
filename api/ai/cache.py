"""In-process grounded-answer cache keyed by question, model and source versions."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date
from hashlib import sha256
from threading import Lock
from typing import Any
from uuid import UUID

from api.ai.rag import RAGContext


def normalize_question(question: str) -> str:
    return " ".join(question.casefold().split())


def source_fingerprint(contexts: list[RAGContext]) -> str:
    parts = []
    for context in sorted(contexts, key=lambda item: str(item.chunk_id)):
        content_hash = sha256(context.content.encode("utf-8")).hexdigest()[:16]
        revision = "" if context.revision is None else str(context.revision)
        parts.append(
            f"{context.chunk_id}:{context.source_version or ''}:{revision}:{content_hash}"
        )
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def answer_cache_key(
    *,
    question: str,
    project_id: UUID | None,
    as_of: date | None,
    model: str,
    fingerprint: str,
) -> str:
    material = "\n".join(
        (
            normalize_question(question),
            "" if project_id is None else str(project_id),
            "" if as_of is None else as_of.isoformat(),
            model,
            fingerprint,
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
