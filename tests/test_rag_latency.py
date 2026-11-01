"""RAG gecikmesi: canlı doğrulama LLM ile paralel, sınırlı ve dürüst kalır.

Ağ, veritabanı ve Ollama gerektirmez.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace

import pytest

from api.ai import live_verify
from api.ai import pipeline as ai_pipeline
from api.ai.cache import answer_cache
from api.ai.live_verify import verify_third_party_contexts
from api.ai.pipeline import execute_answer, iter_answer_events
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context

QUESTION = "Kıdem tazminatı şartları nelerdir?"


def _third_party():
    return replace(court_decision_context(), verification="third_party")


def _as_official(contexts, **kwargs):
    return [replace(context, verification="official") for context in contexts]


# --- portal isteği bütçesi ----------------------------------------------------------


def test_fetch_returns_value_and_reraises_errors():
    assert live_verify._fetch_with_deadline(lambda kind, doc: f"{kind}:{doc}", "yargitay", "1", 1.0) == "yargitay:1"

    def broken(kind, doc):
        raise ValueError("portal hatası")

    with pytest.raises(ValueError):
        live_verify._fetch_with_deadline(broken, "yargitay", "1", 1.0)


def test_fetch_gives_up_at_the_deadline_instead_of_waiting_for_the_portal():
    release = threading.Event()
    started = monotonic()

    with pytest.raises(live_verify._FetchTimeout):
        live_verify._fetch_with_deadline(lambda kind, doc: release.wait(5) or "geç", "yargitay", "1", 0.1)

    assert monotonic() - started < 1.0
    release.set()


def test_verification_stops_at_the_budget_and_does_not_hit_the_portal_again(monkeypatch):
    contexts = [
        replace(court_decision_context(chunk_id="00000000-0000-0000-0000-00000000000a", source_id="00000000-0000-0000-0000-00000000000b"), verification="third_party"),
        replace(court_decision_context(chunk_id="00000000-0000-0000-0000-00000000000c", source_id="00000000-0000-0000-0000-00000000000d"), verification="third_party"),
    ]
    rows = [
        {"id": context.source_id, "external_id": f"yargitay:{index}", "raw_text": context.content}
        for index, context in enumerate(contexts)
    ]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            class Result:
                def fetchall(self):
                    return rows

            return Result()

    monkeypatch.setattr("api.ai.live_verify.database_connection", lambda: Connection())
    release = threading.Event()
    calls: list[str] = []

    def stuck(kind, document_id):
        calls.append(document_id)
        release.wait(5)
        return ""

    started = monotonic()
    result = verify_third_party_contexts(contexts, fetcher=stuck, budget_seconds=0.2)

    assert monotonic() - started < 1.5
    assert calls == ["0"]  # ikinci belge için portala yeni istek atılmadı
    assert result == []
    release.set()


# --- pipeline -----------------------------------------------------------------------


def _settings():
    return SimpleNamespace(
        ai_provider="deepseek", ai_model="m", ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=120.0, ollama_max_output_tokens=768, ollama_num_ctx=3072,
        ollama_keep_alive="30m", rag_query_embedding=False, rag_top_k=2,
        embedding_model="nomic-embed-text", rag_context_chars=800,
    )


@pytest.fixture
def pipeline(monkeypatch):
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", _settings)
    monkeypatch.setattr(
        ai_pipeline, "create_provider", lambda **kwargs: SimpleNamespace(name="deepseek", model="m")
    )
    context = _third_party()
    # Üçüncü taraf atıf, arka planda gerçek doğrulama kuyruğuna (DB) yazmaya çalışır; testte yazılmaz.
    monkeypatch.setattr(ai_pipeline.verification_queue, "enqueue_in_background", lambda ids: None)
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(
        ai_pipeline, "generate_grounded_answer", lambda *args, **kwargs: "İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır. [K1]"
    )
    return SimpleNamespace(module=ai_pipeline, context=context, monkeypatch=monkeypatch)


def _run(request=None):
    """(cevap, zamanlamalar, geçen süre). Süre coroutine içinde ölçülür: `asyncio.run` kapanırken
    arka planda bekleyen iş parçacıklarını da bekler ve bu, cevap süresini yansıtmaz."""
    request = request or AIAnswerRequest(question=QUESTION)

    async def timed():
        started = monotonic()
        response, timings = await execute_answer(request, None)
        return response, timings, monotonic() - started

    return asyncio.run(timed())


def test_verification_finishes_before_generation(pipeline):
    verification_finished = threading.Event()

    def generate(*args, **kwargs):
        assert verification_finished.is_set()
        assert all(c.verification == 'official' for c in kwargs['contexts'])
        return "İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır. [K1]"

    def verify(contexts, **kwargs):
        verification_finished.set()
        return _as_official(contexts)

    pipeline.monkeypatch.setattr(pipeline.module, "generate_grounded_answer", generate)
    pipeline.monkeypatch.setattr(pipeline.module, "verify_third_party_contexts", verify)

    response, timings, elapsed = _run()

    assert elapsed < 2.5
    assert response.citations[0].verification == "official"
    assert timings.extra["live_verify"] == "done"


def test_no_background_verification_when_every_source_is_official(pipeline):
    pipeline.monkeypatch.setattr(pipeline.module, "_retrieve", lambda *a, **k: [court_decision_context()])
    pipeline.monkeypatch.setattr(
        pipeline.module, "verify_third_party_contexts",
        lambda contexts: (_ for _ in ()).throw(AssertionError("gereksiz portal doğrulaması")),
    )

    response, timings, _ = _run()

    assert response.citations[0].verification == "official"
    assert "live_verify" not in timings.extra


def test_slow_verification_uses_only_existing_official_evidence(pipeline):
    release = threading.Event()
    pipeline.monkeypatch.setattr(pipeline.module, "_PRE_GENERATION_VERIFY_WAIT_SECONDS", 0.2)
    official = court_decision_context(chunk_id='00000000-0000-0000-0000-000000000008', source_id='00000000-0000-0000-0000-000000000009')
    pipeline.monkeypatch.setattr(pipeline.module, '_retrieve', lambda *a, **k: [pipeline.context, official])
    pipeline.monkeypatch.setattr(
        pipeline.module, "verify_third_party_contexts",
        lambda contexts, **kwargs: release.wait(2) or _as_official(contexts),
    )

    response, timings, elapsed = _run()

    assert elapsed < 1.5
    assert response.citations[0].verification == "official"
    assert response.citations[0].source_id == official.source_id
    assert timings.extra["live_verify"] == "timeout"
    release.set()


def test_failing_verification_never_falls_back_to_unverified_badge(pipeline):
    def broken(contexts, **kwargs):
        raise RuntimeError("portal çöktü")

    pipeline.monkeypatch.setattr(pipeline.module, "verify_third_party_contexts", broken)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        _run()
    assert error.value.status_code == 422


def test_old_cache_cannot_bypass_required_verification(pipeline):
    pipeline.monkeypatch.setattr(pipeline.module, "verify_third_party_contexts", _as_official)
    first, _, _ = _run()
    assert first.from_cache is False

    release = threading.Event()
    pipeline.monkeypatch.setattr(pipeline.module, "_PRE_GENERATION_VERIFY_WAIT_SECONDS", 0.1)
    pipeline.monkeypatch.setattr(
        pipeline.module, "verify_third_party_contexts", lambda contexts, **kwargs: release.wait(2) or _as_official(contexts)
    )

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        _run()
    assert error.value.status_code == 422
    release.set()


def test_unloading_the_embedding_model_does_not_block_the_event_loop(pipeline):
    loop_thread = threading.get_ident()
    seen: list[int] = []
    pipeline.monkeypatch.setattr(
        pipeline.module, "unload_ollama_model", lambda *args: seen.append(threading.get_ident())
    )
    pipeline.monkeypatch.setattr(pipeline.module, "verify_third_party_contexts", _as_official)

    _run()

    assert seen and seen[0] != loop_thread


def test_sources_found_event_carries_source_preview_but_no_answer_text(pipeline):
    pipeline.monkeypatch.setattr(pipeline.module, "verify_third_party_contexts", _as_official)

    async def collect():
        return [event async for event in iter_answer_events(AIAnswerRequest(question=QUESTION), None)]

    events = asyncio.run(collect())
    found = next(event for event in events if event["stage"] == "sources_found")

    assert found["count"] == 1
    source = found["sources"][0]
    assert source["marker"] == "K1" and source["verification"] == "official"
    assert "Yargıtay" in source["reference"] and source["source_type"] == "court_decision"
    assert "answer" not in found and "result" not in found
    assert "Kıdem tazminatı doğar" not in str(found)  # üretilen metin kaynak özetine sızmaz
