"""Çok turlu sohbet: geçmişin prompta, aramaya ve önbelleğe taşınması.

Veritabanı ve ağ gerektirmez.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.ai.cache import (
    answer_cache,
    answer_cache_key,
    history_fingerprint,
)
from api.ai.conversation_history import (
    ConversationContext,
    ConversationNotFound,
    history_turns_from_rows,
    load_conversation_context,
    retrieval_question,
    strip_markers,
)
from api.ai.pipeline import execute_answer
from api.ai.rag import HistoryTurn, build_grounded_prompt
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context

QUESTION = "Kıdem tazminatına hak kazanma şartları nelerdir?"
ANSWER = "Bir yıllık kıdemi dolduran işçi kıdem tazminatına hak kazanır. [K1] Fesih haklı olmalıdır. [K2]"


def _row(role: str, content: str, **metadata):
    return {"role": role, "content": content, "metadata": metadata}


# --- geçmişin çıkarılması -----------------------------------------------------------


def test_strip_markers_removes_source_markers_and_extra_space():
    assert strip_markers("Hak doğar. [K1] Şart var [ k2 ] .") == "Hak doğar. Şart var ."


def test_history_pairs_questions_with_answers_and_strips_markers():
    turns = history_turns_from_rows(
        [_row("user", QUESTION), _row("assistant", ANSWER, grounded=True)]
    )

    assert turns == (
        HistoryTurn(
            question=QUESTION,
            answer="Bir yıllık kıdemi dolduran işçi kıdem tazminatına hak kazanır. Fesih haklı olmalıdır.",
        ),
    )
    assert "[K" not in turns[0].answer


def test_history_skips_ungrounded_answers():
    turns = history_turns_from_rows(
        [
            _row("user", "Soru bir?"),
            _row("assistant", "Kaynaklarda yeterli bilgi yok.", grounded=False),
            _row("user", QUESTION),
            _row("assistant", ANSWER, grounded=True),
        ]
    )

    assert [turn.question for turn in turns] == [QUESTION]


def test_history_keeps_only_the_latest_turns_and_ignores_unanswered_question():
    rows = []
    for number in range(5):
        rows += [_row("user", f"Soru {number}"), _row("assistant", f"Cevap {number}. [K1]")]
    rows.append(_row("user", "Cevaplanmamış son soru"))

    turns = history_turns_from_rows(rows, max_turns=2)

    assert [turn.question for turn in turns] == ["Soru 3", "Soru 4"]


def test_history_clips_long_text():
    turns = history_turns_from_rows(
        [_row("user", "x" * 1000), _row("assistant", "y" * 1000, grounded=True)]
    )

    assert len(turns[0].question) <= 300
    assert len(turns[0].answer) <= 350
    assert turns[0].answer.endswith("…")


# --- arama sorusu ------------------------------------------------------------------

HISTORY = (HistoryTurn(question=QUESTION, answer="Bir yıl çalışmak gerekir."),)


def test_standalone_question_is_searched_as_is():
    question = "İhbar tazminatı süreleri nasıl hesaplanır?"
    assert retrieval_question(question, HISTORY) == question


def test_without_history_the_question_is_unchanged():
    assert retrieval_question("Peki bunun süresi?", ()) == "Peki bunun süresi?"


def test_follow_up_gets_topic_word_first_and_filler_removed():
    query = retrieval_question("Peki bunun zamanaşımı süresi ne kadar?", HISTORY)

    assert query.startswith("kıdem ")
    assert "zamanaşımı" in query
    assert "peki" not in query.casefold() and "bunun" not in query.casefold()


def test_follow_up_keeps_law_and_article_numbers():
    query = retrieval_question("Peki 4857 sayılı kanun madde 17 ne diyor?", HISTORY)

    assert "4857" in query and "madde 17" in query


def test_empty_follow_up_falls_back_to_previous_question():
    assert QUESTION in retrieval_question("Peki?", HISTORY)


# --- prompt ve önbellek ------------------------------------------------------------


def test_prompt_has_history_block_that_is_not_a_source():
    prompt = build_grounded_prompt(
        "Zamanaşımı süresi nedir?",
        [court_decision_context()],
        history=(HistoryTurn(QUESTION, "Bir yıl çalışmak gerekir."),),
    )

    assert "ÖNCEKİ KONUŞMA" in prompt
    assert "kaynak değildir" in prompt
    assert f"Soru: {QUESTION}" in prompt
    assert prompt.index("ÖNCEKİ KONUŞMA") < prompt.index("KULLANICI SORUSU")
    assert "[K1]" in prompt  # yalnızca yeni kaynağın işareti


def test_prompt_without_history_is_unchanged():
    contexts = [court_decision_context()]

    assert build_grounded_prompt("Soru burada?", contexts) == build_grounded_prompt(
        "Soru burada?", contexts, history=()
    )
    assert "ÖNCEKİ KONUŞMA" not in build_grounded_prompt("Soru burada?", contexts)


def test_cache_key_depends_on_history():
    base = dict(
        question="Peki süresi ne kadar?",
        project_id=None,
        as_of=None,
        model="m",
        fingerprint="f",
    )
    other = (HistoryTurn("Başka konu sorusu?", "Başka cevap."),)

    assert history_fingerprint(()) == ""
    assert answer_cache_key(**base) == answer_cache_key(**base, history_key="")
    assert answer_cache_key(**base, history_key=history_fingerprint(HISTORY)) != answer_cache_key(
        **base, history_key=history_fingerprint(other)
    )


# --- geçmişi veritabanından okuma ---------------------------------------------------


class FakeConnection:
    def __init__(self, conversation, message_rows):
        self.conversation = conversation
        self.message_rows = message_rows

    def execute(self, sql, params=None):
        outer = self

        class Result:
            def fetchone(self):
                return outer.conversation

            def fetchall(self):
                return outer.message_rows

        return Result()


def test_load_context_raises_when_conversation_is_not_visible():
    with pytest.raises(ConversationNotFound):
        load_conversation_context(FakeConnection(None, []), uuid4())


def test_load_context_reverses_newest_first_rows_into_turns():
    project_id = uuid4()
    newest_first = [
        _row("assistant", ANSWER, grounded=True),
        _row("user", QUESTION),
    ]

    context = load_conversation_context(
        FakeConnection({"id": uuid4(), "project_id": project_id}, newest_first), uuid4()
    )

    assert context.project_id == project_id
    assert [turn.question for turn in context.turns] == [QUESTION]


# --- pipeline ----------------------------------------------------------------------


def _settings():
    return SimpleNamespace(
        ai_provider="deepseek",
        ai_model="m",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=120.0,
        ollama_max_output_tokens=768,
        ollama_num_ctx=3072,
        ollama_keep_alive="30m",
        rag_query_embedding=False,
        rag_top_k=2,
        embedding_model="nomic-embed-text",
        rag_context_chars=800,
    )


@pytest.fixture
def pipeline(monkeypatch):
    from api.ai import pipeline as ai_pipeline

    answer_cache.clear()
    calls = SimpleNamespace(retrieve=[], generate=[], persisted=0)
    context = court_decision_context(content='Kıdem tazminatı ve haksız fesih zamanaşımı süresi bu sentetik örnekte iki yıldır.')

    monkeypatch.setattr(ai_pipeline, "get_settings", _settings)
    monkeypatch.setattr(
        ai_pipeline, "create_provider", lambda **kwargs: SimpleNamespace(name="deepseek", model="m")
    )

    def retrieve(request, **kwargs):
        calls.retrieve.append(kwargs.get("question"))
        return [context]

    def generate(provider, **kwargs):
        calls.generate.append(kwargs)
        return f"{context.content} [K1]"

    def persist(request, answer, **kwargs):
        calls.persisted += 1
        return uuid4(), uuid4()

    monkeypatch.setattr(ai_pipeline, "_retrieve", retrieve)
    monkeypatch.setattr(ai_pipeline, "generate_grounded_answer", generate)
    monkeypatch.setattr(ai_pipeline, "persist_answer", persist)

    @contextmanager
    def fake_connection(_user_id):
        yield object()

    monkeypatch.setattr(ai_pipeline, "authenticated_database_connection", fake_connection)
    return ai_pipeline, calls


def _use_context(monkeypatch, ai_pipeline, *, project_id=None, turns=HISTORY):
    monkeypatch.setattr(
        ai_pipeline,
        "load_conversation_context",
        lambda connection, conversation_id: ConversationContext(project_id, tuple(turns)),
    )


def test_follow_up_uses_history_for_search_and_generation(pipeline, monkeypatch):
    ai_pipeline, calls = pipeline
    _use_context(monkeypatch, ai_pipeline)
    request = AIAnswerRequest(
        question="Peki bunun zamanaşımı süresi ne kadar?", conversation_id=uuid4()
    )

    response, _ = asyncio.run(execute_answer(request, uuid4()))

    assert calls.retrieve[0].startswith("kıdem ")
    assert calls.generate[0]["history"] == HISTORY
    assert calls.generate[0]["question"] == request.question  # model asıl soruyu görür
    assert calls.persisted == 1
    assert response.conversation_id is not None


def test_first_turn_has_no_history(pipeline):
    _, calls = pipeline
    request = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")

    asyncio.run(execute_answer(request, uuid4()))

    assert calls.generate[0]["history"] == ()
    assert calls.retrieve[0] == request.question


def test_same_question_with_different_history_is_not_served_from_cache(pipeline, monkeypatch):
    ai_pipeline, calls = pipeline
    question = "Peki süresi ne kadar?"
    other = (HistoryTurn("Haksız fesih nedir?", "Kanunda sayılmayan fesihtir."),)

    _use_context(monkeypatch, ai_pipeline, turns=HISTORY)
    asyncio.run(execute_answer(AIAnswerRequest(question=question, conversation_id=uuid4()), uuid4()))
    _use_context(monkeypatch, ai_pipeline, turns=other)
    asyncio.run(execute_answer(AIAnswerRequest(question=question, conversation_id=uuid4()), uuid4()))
    _use_context(monkeypatch, ai_pipeline, turns=other)
    asyncio.run(execute_answer(AIAnswerRequest(question=question, conversation_id=uuid4()), uuid4()))

    assert len(calls.generate) == 2  # üçüncü çağrı ikincinin önbelleğinden


def test_anonymous_user_cannot_continue_a_conversation(pipeline):
    request = AIAnswerRequest(question="Peki süresi ne kadar?", conversation_id=uuid4())

    with pytest.raises(HTTPException) as error:
        asyncio.run(execute_answer(request, None))

    assert error.value.status_code == 401


def test_unknown_conversation_is_404_before_any_generation(pipeline, monkeypatch):
    ai_pipeline, calls = pipeline

    def missing(connection, conversation_id):
        raise ConversationNotFound(str(conversation_id))

    monkeypatch.setattr(ai_pipeline, "load_conversation_context", missing)
    request = AIAnswerRequest(question="Peki süresi ne kadar?", conversation_id=uuid4())

    with pytest.raises(HTTPException) as error:
        asyncio.run(execute_answer(request, uuid4()))

    assert error.value.status_code == 404
    assert calls.generate == [] and calls.retrieve == []


def test_conversation_of_another_project_is_rejected(pipeline, monkeypatch):
    ai_pipeline, calls = pipeline
    _use_context(monkeypatch, ai_pipeline, project_id=uuid4())
    request = AIAnswerRequest(
        question="Peki süresi ne kadar?", conversation_id=uuid4(), project_id=uuid4()
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(execute_answer(request, uuid4()))

    assert error.value.status_code == 409
    assert calls.generate == []
