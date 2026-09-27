"""Offline end-to-end checks of the evidence gate, including legacy cache hits."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.ai import pipeline
from api.ai.cache import AnswerCache, answer_cache_key, source_fingerprint
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context


@pytest.fixture
def isolated_pipeline(monkeypatch):
    context = court_decision_context(content="Bu olayda talep reddedilmelidir.")
    cache = AnswerCache()
    persisted = []
    settings = SimpleNamespace(
        ai_provider="deepseek", ai_model="offline-test",
        ollama_base_url="http://127.0.0.1:11434", ollama_timeout_seconds=1,
        ollama_max_output_tokens=512, ollama_num_ctx=3072, ollama_keep_alive="30m",
        rag_query_embedding=False, rag_top_k=2, embedding_model="test",
        rag_context_chars=800,
    )
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "answer_cache", cache)
    monkeypatch.setattr(pipeline, "create_provider", lambda **kw: SimpleNamespace(name="fake", model="offline-test"))
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [context])
    # Do not touch local models, worker pause files, the DB or official portals.
    for name in ("pause_embeddings", "resume_embeddings", "unload_ollama_model",
                 "verify_pending_statute", "verify_relevant_pending_statute"):
        if hasattr(pipeline, name):
            monkeypatch.setattr(pipeline, name, lambda *a, **kw: None)
    monkeypatch.setattr(pipeline, "verify_third_party_contexts", lambda items: items)
    monkeypatch.setattr(pipeline.verification_queue, "enqueue_in_background", lambda ids: None)

    def persist(request, answer, **kwargs):
        persisted.append(answer)
        return uuid4(), uuid4()

    monkeypatch.setattr(pipeline, "persist_answer", persist)
    request = AIAnswerRequest(question="Bu olayda talep nasıl değerlendirilmiştir?")
    key = answer_cache_key(
        question=request.question, project_id=None, as_of=None,
        model="offline-test", fingerprint=source_fingerprint([context]),
    )
    return SimpleNamespace(context=context, cache=cache, request=request, key=key, persisted=persisted)


def test_supported_marker_cannot_hide_contradiction_or_persist_it(monkeypatch, isolated_pipeline):
    state = isolated_pipeline
    bad = "Bu olayda talep kabul edilmelidir. [K1]"
    monkeypatch.setattr(pipeline, "generate_grounded_answer", lambda *a, **kw: bad)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(pipeline.execute_answer(state.request, uuid4()))
    assert raised.value.status_code == 422
    assert state.persisted == []
    assert len(state.cache) == 0

    async def collect():
        return [event async for event in pipeline.iter_answer_events(state.request, uuid4())]

    events = asyncio.run(collect())
    assert events[-1]["stage"] == "error"
    assert events[-1]["status"] == 422
    assert all("result" not in event for event in events)
    assert bad not in str(events)
    assert state.persisted == []


@pytest.mark.parametrize("bad_answer,missing_source", [
    ("Bu olayda talep kabul edilmelidir. [K1]", False),
    ("Bu olayda talep reddedilmelidir. [K1] [K99]", False),
    ("Bu olayda talep reddedilmelidir. [K1]", True),
])
def test_legacy_cache_is_revalidated_not_trusted(monkeypatch, isolated_pipeline, bad_answer, missing_source):
    state = isolated_pipeline
    state.cache.put(state.key, {
        "answer": bad_answer,
        "citations": [{"chunk_id": str(uuid4() if missing_source else state.context.chunk_id)}],
        "grounded": True,
    })
    calls = []
    safe = f"{state.context.content} [K1]"

    def generate(*args, **kwargs):
        calls.append(True)
        return safe

    monkeypatch.setattr(pipeline, "generate_grounded_answer", generate)
    response, timings = asyncio.run(pipeline.execute_answer(state.request, uuid4()))
    assert calls == [True]
    assert response.answer == safe
    assert response.grounded
    assert not response.from_cache and not timings.from_cache
    assert len(state.persisted) == 1
    assert state.persisted[0].text == safe
    assert state.cache.get(state.key)["answer"] == safe

    cached, timings = asyncio.run(pipeline.execute_answer(state.request, uuid4()))
    assert calls == [True]
    assert cached.from_cache and timings.from_cache
    assert cached.grounded and cached.answer == safe


def test_legacy_third_party_cache_cannot_bypass_official_verification(monkeypatch, isolated_pipeline):
    state = isolated_pipeline
    context = replace(state.context, verification="third_party")
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [context])
    state.cache.put(state.key, {
        "answer": f"{context.content} [K1]",
        "citations": [{"chunk_id": str(context.chunk_id)}],
        "grounded": True,
    })
    def unexpected_generation(*args, **kwargs):
        pytest.fail("Unverified evidence must never reach generation")
    monkeypatch.setattr(pipeline, "generate_grounded_answer", unexpected_generation)
    for _ in range(2):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(pipeline.execute_answer(state.request, uuid4()))
        assert raised.value.status_code == 422
    assert state.persisted == []
