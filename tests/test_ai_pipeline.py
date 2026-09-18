from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.ai.cache import (
    answer_cache,
    answer_cache_key,
    normalize_question,
    source_fingerprint,
)
from api.ai.eval_questions import REGRESSION_QUESTIONS
from api.ai.pipeline import execute_answer, iter_answer_events
from api.ai.retrieval import LEXICAL_RETRIEVAL_SQL, LEXICAL_HISTORICAL_SQL
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context


def _settings(**overrides):
    values = dict(
        ai_provider="deepseek",
        ai_model="deepseek-r1:8b",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=120.0,
        ollama_max_output_tokens=768,
        ollama_num_ctx=1536,
        ollama_keep_alive="30m",
        rag_query_embedding=False,
        rag_top_k=2,
        embedding_model="nomic-embed-text",
        rag_context_chars=800,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_regression_set_covers_required_topics():
    topics = {item["topic"] for item in REGRESSION_QUESTIONS}
    assert len(REGRESSION_QUESTIONS) == 20
    assert {
        "kıdem tazminatı",
        "haksız fesih",
        "yıllık izin",
        "zamanaşımı",
        "idari işlem",
        "Anayasa Mahkemesi kararı",
        "mevzuat maddesi",
    }.issubset(topics)


def test_lexical_sql_uses_and_query_and_defers_detail_joins():
    assert "ORDER BY ord LIMIT 2" in LEXICAL_RETRIEVAL_SQL
    assert "ts_debug('turkish'" in LEXICAL_RETRIEVAL_SQL
    assert "legal_rag_current_lexical_hits" in LEXICAL_RETRIEVAL_SQL
    assert LEXICAL_RETRIEVAL_SQL.index("legal_rag_current_lexical_hits") < LEXICAL_RETRIEVAL_SQL.index(
        "LEFT JOIN court_decision_details"
    )
    assert "CAST(%(as_of)s AS date) IS NOT NULL" in LEXICAL_HISTORICAL_SQL
    assert "verified_against_gazette" in LEXICAL_HISTORICAL_SQL
    assert "verified_against_mbs" in LEXICAL_HISTORICAL_SQL


def test_cache_key_changes_when_source_version_changes():
    first = court_decision_context()
    second = court_decision_context()
    object.__setattr__(second, "source_version", "2")
    assert source_fingerprint([first]) != source_fingerprint([second])
    assert normalize_question("  Kıdem  Tazminatı ") == "kıdem tazminatı"
    key_one = answer_cache_key(
        question="Kıdem tazminatı",
        project_id=None,
        as_of=None,
        model="deepseek-r1:8b",
        fingerprint=source_fingerprint([first]),
    )
    key_two = answer_cache_key(
        question="kıdem   tazminatı",
        project_id=None,
        as_of=None,
        model="deepseek-r1:8b",
        fingerprint=source_fingerprint([first]),
    )
    assert key_one == key_two


def test_answer_cache_skips_generation_on_same_sources(monkeypatch):
    from api.ai import pipeline as ai_pipeline

    context = court_decision_context()
    answer_cache.clear()
    generated = {"count": 0}

    def generate(*args, **kwargs):
        generated["count"] += 1
        return "Kıdem tazminatı doğar. [K1]"

    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(ai_pipeline, "generate_grounded_answer", generate)

    request = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")
    first, first_timings = asyncio.run(execute_answer(request, None))
    second, second_timings = asyncio.run(execute_answer(request, None))

    assert generated["count"] == 1
    assert first.answer == second.answer
    assert first.from_cache is False
    assert second.from_cache is True
    assert second_timings.from_cache is True
    assert first.grounded and second.grounded


def test_answer_cache_misses_when_source_hash_changes(monkeypatch):
    from api.ai import pipeline as ai_pipeline

    first = court_decision_context()
    second = court_decision_context()
    object.__setattr__(second, "content", first.content + " ek cümle")
    answer_cache.clear()
    generated = {"count": 0}

    def retrieve(*args, **kwargs):
        return [second] if generated["count"] else [first]

    def generate(*args, **kwargs):
        generated["count"] += 1
        return "Kıdem tazminatı doğar. [K1]"

    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )
    monkeypatch.setattr(ai_pipeline, "_retrieve", retrieve)
    monkeypatch.setattr(ai_pipeline, "generate_grounded_answer", generate)

    request = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")
    asyncio.run(execute_answer(request, None))
    asyncio.run(execute_answer(request, None))
    assert generated["count"] == 2


def test_generation_lock_serializes_two_requests(monkeypatch):
    from api.ai import pipeline as ai_pipeline
    import time

    context = court_decision_context()
    answer_cache.clear()
    active = {"now": 0, "max": 0}

    def blocking_generate(*args, **kwargs):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        active["now"] -= 1
        return "Kıdem tazminatı doğar. [K1]"

    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(ai_pipeline, "generate_grounded_answer", blocking_generate)

    request_a = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")
    request_b = AIAnswerRequest(question="Haksız fesih sonuçları nelerdir?")

    async def both():
        return await asyncio.gather(
            execute_answer(request_a, None),
            execute_answer(request_b, None),
        )

    asyncio.run(both())
    assert active["max"] == 1


def test_progress_events_do_not_include_unverified_text(monkeypatch):
    from api.ai import pipeline as ai_pipeline

    context = court_decision_context()
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(
        ai_pipeline,
        "generate_grounded_answer",
        lambda *args, **kwargs: "Kıdem tazminatı doğar. [K1]",
    )

    async def collect():
        events = []
        async for event in iter_answer_events(
            AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"),
            None,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())
    stages = [event["stage"] for event in events]
    assert stages[0] == "searching"
    assert "sources_found" in stages
    assert "generating" in stages
    assert "verifying" in stages
    assert stages[-1] == "done"
    assert "result" not in events[stages.index("generating")]
    assert events[-1]["result"]["answer"].endswith("[K1]")
    assert events[-1]["result"]["grounded"] is True


def test_ungrounded_progress_emits_error_without_answer_body(monkeypatch):
    from api.ai import pipeline as ai_pipeline

    context = court_decision_context()
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        ai_pipeline,
        "create_provider",
        lambda **kwargs: SimpleNamespace(name="deepseek", model="deepseek-r1:8b"),
    )
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(
        ai_pipeline,
        "generate_grounded_answer",
        lambda *args, **kwargs: "Kaynaksız hukuki sonuç.",
    )

    async def collect():
        events = []
        async for event in iter_answer_events(
            AIAnswerRequest(question="Haksız fesih nedir acaba?"),
            None,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())
    assert events[-1]["stage"] == "error"
    assert events[-1]["status"] == 422
    assert all("result" not in event or event.get("result") is None for event in events)
