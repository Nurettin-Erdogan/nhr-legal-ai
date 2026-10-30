"""Pre-computed, source-verified answers for common general legal questions.

An entry is a finished answer (text + the sources it cites) stored by `scripts/warm_answer_cache.py`. Serving one skips the search,
the planner, the writer and the checker: the reply is instant. It is reused ONLY if every cited chunk is still exactly what the answer
was built on (same version, revision and content digest) and still passes the official / verified / current filters; otherwise it is
ignored and the normal pipeline runs. No user data is ever stored here, live traffic never writes to this table, and a cached answer is
never treated as proof of anything beyond that unchanged, verified evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import asdict
from datetime import date
from hashlib import sha256
from uuid import UUID

import psycopg

from api.ai.rag import RAGContext
from api.ai.search_plan import normalize
from api.ai.verification import VerifiedAnswer

# Bump when the answer-making logic changes in a way that should retire every stored answer.
ANSWER_PIPELINE_VERSION = "free-answer-2026-10-31"

# While the warm-up script runs, the pipeline hands every cacheable finished answer to this callable: (question, answer, model).
collector: ContextVar[Callable[[str, VerifiedAnswer, str], None] | None] = ContextVar("warm_cache_collector", default=None)

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def question_key(question: str) -> str:
    """Case, punctuation and spacing do not make a different question; a different word or number does."""
    return " ".join(_NON_WORD.sub(" ", normalize(question)).split())


def context_to_json(context: RAGContext) -> dict:
    data = asdict(context)
    return {key: (str(value) if isinstance(value, UUID) else value.isoformat() if isinstance(value, date) else value)
            for key, value in data.items()}


def context_from_json(data: dict) -> RAGContext:
    converted = dict(data)
    for key in ("chunk_id", "source_id"):
        converted[key] = UUID(converted[key])
    for key in ("decision_date", "version_date", "effective_from", "effective_to"):
        if converted.get(key):
            converted[key] = date.fromisoformat(converted[key])
    return RAGContext(**converted)


def state_fingerprint(rows: list[RAGContext]) -> str:
    """Digest of the CURRENT stored state of the chunks (id, version, revision, text)."""
    parts = sorted(f"{row.chunk_id}:{row.source_version or ''}:{'' if row.revision is None else row.revision}:"
                   f"{sha256(row.content.encode('utf-8')).hexdigest()}" for row in rows)
    return sha256("|".join(parts).encode("utf-8")).hexdigest()


def _current_chunks(connection: psycopg.Connection, chunk_ids: list[str]) -> list[RAGContext]:
    from api.ai.retrieval import CHUNKS_BY_ID_SQL, _execute_retrieval
    return _execute_retrieval(connection, CHUNKS_BY_ID_SQL, {"chunk_ids": chunk_ids, "as_of": None}, timeout="5s")


def lookup(connection: psycopg.Connection, question: str) -> VerifiedAnswer | None:
    """The stored answer for this question when its evidence is unchanged, else None. Never raises for a bad or stale row."""
    try:
        row = connection.execute(
            "SELECT answer_text, answer_kind, contexts, source_fingerprint FROM verified_answer_cache "
            "WHERE question_key = %s AND pipeline_version = %s", (question_key(question), ANSWER_PIPELINE_VERSION)).fetchone()
        if row is None:
            return None
        contexts = [context_from_json(item) for item in (row["contexts"] if isinstance(row["contexts"], list) else json.loads(row["contexts"]))]
        current = _current_chunks(connection, [str(context.chunk_id) for context in contexts])
        if len(current) != len(contexts) or state_fingerprint(current) != row["source_fingerprint"]:
            return None
        if row["answer_kind"] != "legal" or not contexts:
            return None
        return VerifiedAnswer(text=row["answer_text"], contexts=tuple(contexts), unverified_markers=())
    except (psycopg.Error, KeyError, ValueError, TypeError):
        return None


def store(connection: psycopg.Connection, question: str, answer: VerifiedAnswer, model: str) -> bool:
    """Write (or replace) an entry. Only for a grounded 'legal' answer whose cited chunks can be read back unchanged."""
    if not answer.grounded or answer.answer_kind != "legal" or not answer.contexts:
        return False
    current = _current_chunks(connection, [str(context.chunk_id) for context in answer.contexts])
    if len(current) != len(answer.contexts):
        return False
    connection.execute(
        "INSERT INTO verified_answer_cache (question_key, pipeline_version, question_text, answer_text, answer_kind, contexts, "
        "source_fingerprint, model) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
        "ON CONFLICT (question_key, pipeline_version) DO UPDATE SET question_text = EXCLUDED.question_text, "
        "answer_text = EXCLUDED.answer_text, answer_kind = EXCLUDED.answer_kind, contexts = EXCLUDED.contexts, "
        "source_fingerprint = EXCLUDED.source_fingerprint, model = EXCLUDED.model, created_at = now()",
        (question_key(question), ANSWER_PIPELINE_VERSION, question.strip(), answer.text, answer.answer_kind,
         json.dumps([context_to_json(context) for context in answer.contexts], ensure_ascii=False),
         state_fingerprint(current), model))
    return True
