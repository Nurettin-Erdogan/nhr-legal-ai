"""Assistant routing integration, isolated from all models, portals and databases."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import conversations
from api.ai import pipeline
from api.ai.cache import answer_cache
from api.ai.conversation_history import ConversationContext, prior_questions_from_rows
from api.ai.pipeline import persist_answer as real_persist_answer
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context, document_context, legislation_context


def _never(name):
    def fail(*args, **kwargs):
        pytest.fail(f"Unexpected external or bypassed operation: {name}")
    return fail


def _settings():
    return SimpleNamespace(
        ai_provider="ollama", ai_model="test-local", ollama_base_url="http://model.invalid",
        ollama_timeout_seconds=10, ollama_max_output_tokens=0, ollama_num_ctx=3072,
        ollama_keep_alive="30m", rag_query_embedding=False, rag_top_k=4,
        embedding_model="test-embedding", rag_context_chars=2400,
        rag_natural_answers=True, rag_explanations=False, cloud_ai_provider="",
    )


@pytest.fixture
def routing(monkeypatch):
    """The actual execute_answer runs; every external boundary is fake or fails."""
    answer_cache.clear()
    calls = []
    settings = _settings()
    provider = SimpleNamespace(name="ollama", model="test-local", generate=_never("model generation"))
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "create_provider", lambda **kwargs: calls.append("provider") or provider)
    monkeypatch.setattr(pipeline, "pause_embeddings", lambda *args: calls.append("pause"))
    monkeypatch.setattr(pipeline, "resume_embeddings", lambda *args: calls.append("resume"))
    monkeypatch.setattr(pipeline, "unload_ollama_model", lambda *args: calls.append("unload"))
    monkeypatch.setattr(pipeline, "try_fast_statute", lambda **kwargs: calls.append("fast_lookup") or [])
    monkeypatch.setattr(pipeline, "lookup_event_basis", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "_planned_statutes", lambda *args, **kwargs: [])
    monkeypatch.setattr(pipeline, "_retrieve", lambda *args, **kwargs: calls.append("retrieval") or [])
    for name in (
        "_embed_question", "create_embedding_provider", "generate_grounded_answer",
        "verify_pending_statute", "verify_relevant_pending_statute",
        "verify_third_party_contexts", "_start_live_verification",
        "database_connection", "authenticated_database_connection", "persist_answer",
    ):
        monkeypatch.setattr(pipeline, name, _never(name))
    monkeypatch.setattr(pipeline.verification_queue, "enqueue_in_background", lambda ids: None)
    yield SimpleNamespace(calls=calls, settings=settings, provider=provider)
    answer_cache.clear()


def _execute(request, user_id=None):
    events = []
    response, timings = asyncio.run(pipeline.execute_answer(request, user_id, on_stage=events.append))
    return response, timings, events


def test_greeting_short_circuits_models_search_embedding_and_background_pause(routing):
    request = AIAnswerRequest(question="  Merhaba!  ")
    response, timings, events = _execute(request)

    assert routing.calls == []
    assert response.question == "Merhaba!"
    assert response.answer == "Merhaba! Nasıl yardımcı olabilirim?"
    assert response.provider == "application"
    assert response.model == "conversation-router-v1"
    assert response.answer_kind == "conversation"
    assert response.grounded is False
    assert response.citations == response.consulted_sources == response.unverified_markers == []
    assert response.search_summary is None
    assert response.from_cache is False
    assert timings.embedding_ms == timings.llm_ms == 0
    assert [event["stage"] for event in events] == ["done"]
    assert events[0]["result"]["answer_kind"] == "conversation"
    assert events[0]["result"]["grounded"] is False
    assert len(answer_cache) == 0


def test_mixed_greeting_and_legal_question_is_not_a_social_shortcut(routing):
    response, _, events = _execute(AIAnswerRequest(question="Merhaba, kıdem tazminatı şartları nelerdir?"))
    assert "provider" in routing.calls and "retrieval" in routing.calls
    assert routing.calls.index("pause") < routing.calls.index("fast_lookup")
    assert routing.calls[-1] == "resume"
    assert response.answer_kind == "insufficient_sources"
    assert response.answer != "Merhaba! Nasıl yardımcı olabilirim?"
    assert [event["stage"] for event in events][0] == "searching"
    assert [event["stage"] for event in events][-1] == "done"


@pytest.mark.parametrize("question", [
    "pizza tarifi verirmisin", "Bana pizza tarifi verir misin?",
    "En iyi pizza tarifi nedir?", "Kek nasıl yapılır?", "Bugün hava nasıl?",
])
def test_explicit_nonlegal_request_needs_neither_search_nor_paid_model(routing, question):
    response, timings, events = _execute(AIAnswerRequest(question=question))
    assert routing.calls == []
    assert "hukuki bir soru değil" in response.answer
    assert response.model == "scope-router-v1"
    assert response.answer_kind == "conversation"
    assert response.grounded is False and response.citations == []
    assert response.search_summary is None
    assert timings.embedding_ms == timings.llm_ms == 0
    assert [e["stage"] for e in events] == ["done"]


@pytest.mark.parametrize("question", [
    "Pizza siparişim gelmedi, paramı geri alabilir miyim?",
    "Pizza tarifimi izinsiz yayınladılar, ne yapabilirim?",
    "Pizza tarifi ver, sonra kira artışını açıkla.",
    "Komşum ağacımı kesti, ne yapabilirim?", "Peki bunu nasıl yaparım?",
])
def test_food_legal_disputes_mixed_requests_and_followups_are_not_rejected(routing, question):
    _execute(AIAnswerRequest(question=question))
    assert "retrieval" in routing.calls


def test_nonlegal_fast_reply_still_requires_ownership_of_saved_conversation(routing):
    with pytest.raises(HTTPException) as exc:
        _execute(AIAnswerRequest(question="Pizza tarifi verir misin?", conversation_id=uuid4()))
    assert exc.value.status_code == 401
    assert routing.calls == []


def test_cloud_answer_does_not_pause_or_unload_bulk_embeddings(routing, monkeypatch):
    cloud = SimpleNamespace(name='openrouter', model='test-cloud')
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)
    response, _, _ = _execute(AIAnswerRequest(question='İşçinin hakları nelerdir?'))
    assert response.answer_kind == 'insufficient_sources'
    assert 'retrieval' in routing.calls
    assert not {'pause', 'resume', 'unload'} & set(routing.calls)


def test_failed_shared_embedding_time_is_measured_and_m3_is_kept(routing, monkeypatch):
    routing.settings.rag_query_embedding = True
    seen = []

    async def shared(question):
        await asyncio.sleep(0.001)
        return None

    async def legislation(question):
        return [0.2]

    def retrieve(*a, **kwargs):
        seen.append(kwargs)
        return []

    monkeypatch.setattr(pipeline, '_embed_question', shared)
    monkeypatch.setattr(pipeline, '_embed_legislation_question', legislation)
    monkeypatch.setattr(pipeline, '_retrieve', retrieve)
    _, timings, _ = _execute(AIAnswerRequest(question='İşçinin hakları nelerdir?'))
    assert timings.embedding_ms > 0
    assert timings.extra['query_embeddings'] == dict(shared_ready=False, legislation_ready=True)
    assert seen[0]['legislation_embedding'] == [0.2]


@pytest.mark.parametrize("field", ["project_id", "case_id", "office_project_id", "selected_document_ids"])
def test_anonymous_social_turn_cannot_attach_to_private_scope(routing, field):
    value = [uuid4()] if field == "selected_document_ids" else uuid4()
    events = []
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="merhaba", **{field: value}), None, on_stage=events.append))
    assert error.value.status_code == 401
    assert events == [] and routing.calls == []


def test_anonymous_social_turn_cannot_continue_an_existing_conversation(routing):
    events = []
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="merhaba", conversation_id=uuid4()), None, on_stage=events.append))
    assert error.value.status_code == 401
    assert events == [] and routing.calls == []


def test_existing_conversation_is_loaded_under_the_current_users_rls_before_social_reply(routing, monkeypatch):
    owner, conversation_id = uuid4(), uuid4()
    seen = []

    @contextmanager
    def authenticated(user_id):
        assert user_id == str(owner)
        def execute(sql, params):
            seen.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)
        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(pipeline, "authenticated_database_connection", authenticated)
    events = []
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="merhaba", conversation_id=conversation_id), owner, on_stage=events.append))
    assert error.value.status_code == 404
    assert len(seen) == 1 and seen[0][1] == (conversation_id,)
    assert events == [] and routing.calls == []


@pytest.mark.parametrize("field", ["project_id", "case_id", "office_project_id", "selected_document_ids"])
def test_social_fastpath_cannot_change_an_existing_conversations_scope(routing, monkeypatch, field):
    value = (uuid4(),) if field == "selected_document_ids" else uuid4()
    context = ConversationContext(project_id=None, turns=(), **({} if field == "project_id" else {field: value}))
    if field == "project_id":
        context = replace(context, project_id=value)

    @contextmanager
    def authenticated(user_id):
        yield object()

    monkeypatch.setattr(pipeline, "authenticated_database_connection", authenticated)
    monkeypatch.setattr(pipeline, "load_conversation_context", lambda *args: context)
    events = []
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="merhaba", conversation_id=uuid4()), uuid4(), on_stage=events.append))
    assert error.value.status_code == 409
    assert events == [] and routing.calls == []


def test_social_reply_kind_persists_and_roundtrips_without_becoming_grounded(routing, monkeypatch):
    # Use the real persist_answer/record_exchange rather than fabricating response
    # metadata; only the authenticated connection and audit sink are isolated.
    owner = uuid4()
    executed = []

    @contextmanager
    def authenticated(user_id):
        assert user_id == str(owner)
        yield SimpleNamespace(execute=lambda sql, params: executed.append((sql, params)))

    monkeypatch.setattr(pipeline, "authenticated_database_connection", authenticated)
    monkeypatch.setattr(pipeline, "persist_answer", real_persist_answer)
    monkeypatch.setattr(pipeline, "record_event", lambda *args, **kwargs: None)
    response, _, events = _execute(AIAnswerRequest(question="merhaba"), owner)
    assistant_params = executed[2][1]
    metadata = assistant_params[-1].obj
    assert metadata["answer_kind"] == "conversation" and metadata["grounded"] is False
    assert response.conversation_id == executed[0][1][0]
    assert response.message_id == assistant_params[0]
    assert "RETURNING" not in " ".join(sql for sql, _ in executed)
    assert len(executed) == 3  # conversation + user + assistant; no citations
    assert events[-1]["result"]["conversation_id"] == str(response.conversation_id)

    saved = conversations.build_messages([{
        "id": response.message_id, "role": "assistant", "content": response.answer,
        "created_at": datetime.now(timezone.utc), "model_name": response.model, "metadata": metadata,
    }], [])
    assert saved[0].answer_kind == "conversation" and saved[0].grounded is False
    assert saved[0].citations == []


@pytest.mark.parametrize("kind", [None, "unknown", "legal", "conversation_override", {"conversation": True}, ["conversation"]])
def test_old_or_unknown_stored_answer_kind_defaults_to_legal(kind):
    metadata = {"grounded": False}
    if kind is not None:
        metadata["answer_kind"] = kind
    saved = conversations.build_messages([{
        "id": uuid4(), "role": "assistant", "content": "Eski yanıt",
        "created_at": datetime.now(timezone.utc), "model_name": "old-model", "metadata": metadata,
    }], [])
    assert saved[0].answer_kind == "legal" and saved[0].grounded is False


@pytest.mark.parametrize("question", ["", " ", "\t\n", "\r\n   "])
def test_blank_questions_are_rejected_before_any_routing(question):
    with pytest.raises(ValidationError):
        AIAnswerRequest(question=question)


def test_one_character_nonblank_input_is_still_permitted(routing):
    request = AIAnswerRequest(question=" x ")
    assert request.question == "x"
    response, _, events = _execute(request)
    assert response.answer_kind == "insufficient_sources"
    assert events[-1]["stage"] == "done"


@pytest.mark.parametrize("question", ["4857 sayılı İş Kanunu madde 25 nedir?", "Kıdem tazminatı şartları nelerdir?"])
@pytest.mark.parametrize("pending_source", [False, True])
def test_natural_mode_never_fetches_portals_and_returns_honest_empty_sources_status(routing, monkeypatch, question, pending_source):
    candidate = replace(court_decision_context(), verification="third_party")
    def retrieve(*args, **kwargs):
        routing.calls.append("retrieval")
        return [candidate] if pending_source else []
    monkeypatch.setattr(pipeline, "_retrieve", retrieve)
    response, timings, events = _execute(AIAnswerRequest(question=question))

    assert "retrieval" in routing.calls
    assert response.answer_kind == "insufficient_sources"
    assert response.grounded is False
    assert response.citations == response.consulted_sources == []
    assert response.unverified_markers == []
    assert "kaynaklarımızda bulamadım" in response.answer
    assert response.model == "conversation-router-v1"  # no claim of model generation
    assert response.from_cache is False
    assert "on_demand_legislation" not in timings.extra
    assert "on_demand_relevant_legislation" not in timings.extra
    assert "live_verify" not in timings.extra
    assert events[-1]["stage"] == "done"
    assert events[-1]["result"]["answer_kind"] == "insufficient_sources"
    assert events[-1]["result"]["grounded"] is False
    assert not any(event["stage"] == "verifying_source" for event in events)
    assert len(answer_cache) == 0


def test_social_history_does_not_displace_the_previous_legal_topic():
    rows = [
        {"role": "user", "content": "Kıdem tazminatı nasıl hesaplanır?"},
        {"role": "assistant", "content": "Kaynak gerekiyor.", "metadata": {"grounded": False, "answer_kind": "insufficient_sources"}},
    ]
    for question in ("merhaba", "nasılsın", "teşekkürler", "selam"):
        rows.extend([
            {"role": "user", "content": question},
            {"role": "assistant", "content": "Sosyal yanıt.", "metadata": {"grounded": False, "answer_kind": "conversation"}},
        ])
    assert prior_questions_from_rows(rows) == ("Kıdem tazminatı nasıl hesaplanır?",)


def test_legacy_and_unknown_kinds_are_not_silently_removed_from_followup_context():
    rows = [
        {"role": "user", "content": "İhbar tazminatı nedir?"},
        {"role": "assistant", "content": "Eski yanıt.", "metadata": {}},
        {"role": "user", "content": "Peki bunun süresi?"},
        {"role": "assistant", "content": "Yeni yanıt.", "metadata": {"answer_kind": "unknown"}},
    ]
    assert prior_questions_from_rows(rows) == ("İhbar tazminatı nedir?", "Peki bunun süresi?")


class _SynthesisProvider:
    name = "ollama"
    model = "test-natural"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        assert self.responses, "Unexpected model helper call beyond writer/checker"
        return json.dumps(self.responses.pop(0), ensure_ascii=False)


_NATURAL_QUESTION = "Başvuru süresi ne zaman başlar?"
_NATURAL_TEXT = "Başvuru süresinin başlangıcı tebliğ tarihidir."
_SOURCE_TEXT = "Başvuru süresi tebliğ tarihinden başlar."


def _draft():
    return {"claims": [{"text": _NATURAL_TEXT, "evidence": [{"source": 1, "quote": _SOURCE_TEXT}]}], "question": None}


def _verdict(*, supported=True):
    return {
        "claims": [{"id": 1, "supported": supported, "relevant": True, "scope_preserved": True}],
        "coverage_preserved": True, "source_only": True, "clarification_safe": True,
    }


def _use_actual_synthesis(monkeypatch, routing, *, contexts=None, responses=None):
    provider = _SynthesisProvider(responses or [_draft(), _verdict()])
    monkeypatch.setattr(pipeline, "create_provider", lambda **kwargs: provider)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *args, **kwargs: list(contexts or [legislation_context(content=_SOURCE_TEXT)]))
    return provider


def test_owned_general_conversation_keeps_current_rule_lookup_after_greeting(routing, monkeypatch):
    conversation_id, owner = uuid4(), uuid4()
    _use_actual_synthesis(monkeypatch, routing)
    seen = []
    async def loaded(request, user_id):
        assert request.conversation_id == conversation_id and user_id == owner
        seen.append("ownership_checked")
        return (), ()
    def lookup(**kwargs):
        assert seen == ["ownership_checked"]
        assert kwargs["conversation_id"] is None and kwargs["project_id"] is None
        seen.append("lookup")
        return [legislation_context(content=_SOURCE_TEXT)]
    monkeypatch.setattr(pipeline, "_load_history", loaded)
    monkeypatch.setattr(pipeline, "try_fast_statute", lookup)
    monkeypatch.setattr(pipeline, "_retrieve", _never("unnecessary full discovery after a general greeting"))
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (conversation_id, uuid4()))
    response, _, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION, conversation_id=conversation_id), owner)
    assert response.grounded and seen == ["ownership_checked", "lookup"]


@pytest.mark.parametrize("field", ["project_id", "case_id", "office_project_id"])
def test_scoped_conversation_never_gets_the_general_conversation_fastpath(routing, monkeypatch, field):
    conversation_id, scope = uuid4(), uuid4()
    _use_actual_synthesis(monkeypatch, routing)
    async def loaded(*args):
        return (), ()
    def lookup(**kwargs):
        assert kwargs["conversation_id"] == conversation_id and kwargs["project_id"] == scope
        return []
    monkeypatch.setattr(pipeline, "_load_history", loaded)
    monkeypatch.setattr(pipeline, "try_fast_statute", lookup)
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (conversation_id, uuid4()))
    response, _, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION, conversation_id=conversation_id, **{field: scope}), uuid4())
    assert response.grounded


def test_actual_natural_pipeline_returns_checked_paraphrase_not_quotes_or_secondary_summaries(routing, monkeypatch):
    from api.ai import explanation, statute_summary
    from api.ai.synthesis import CHECK_INSTRUCTION, WRITE_INSTRUCTION

    routing.settings.rag_explanations = True  # Must not invoke the legacy helper regardless.
    provider = _use_actual_synthesis(monkeypatch, routing)
    monkeypatch.setattr(explanation, "explain_verified_answer", _never("legacy explanation"))
    monkeypatch.setattr(statute_summary, "eligible", _never("legacy statute summary"))
    response, timings, events = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))

    assert response.answer == _NATURAL_TEXT + " [K1]"
    assert response.answer != _SOURCE_TEXT + " [K1]"
    assert response.grounded is True and response.answer_kind == "legal"
    assert response.summary == [] and len(response.citations) == 1
    assert response.citations[0].excerpt == _SOURCE_TEXT
    assert response.unverified_markers == []
    assert timings.extra["answer_mode"] == "synthesis"
    assert [call["system_instruction"] for call in provider.calls] == [WRITE_INSTRUCTION, CHECK_INSTRUCTION]
    assert events[-1]["result"]["grounded"] is True
    assert not provider.responses and not response.from_cache
    assert len(answer_cache) == 0


def test_natural_answers_are_rechecked_on_identical_repeated_requests_not_blindly_cached(routing, monkeypatch):
    provider = _use_actual_synthesis(monkeypatch, routing, responses=[_draft(), _verdict(), _draft(), _verdict()])
    request = AIAnswerRequest(question=_NATURAL_QUESTION)
    first, _, _ = _execute(request)
    assert len(provider.calls) == 2 and not first.from_cache
    second, _, _ = _execute(request)
    assert first.answer == second.answer == _NATURAL_TEXT + " [K1]"
    assert first.grounded and second.grounded
    assert len(provider.calls) == 4 and not second.from_cache
    assert len(answer_cache) == 0


def test_verified_cloud_prose_reuses_proof_but_changed_source_requires_new_generation(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name="openrouter", model="cloud-test")
    routing.settings.free_answer_enabled = True
    calls = []
    monkeypatch.setattr(pipeline, "answer_provider", lambda *a, **kw: cloud)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [source])

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        calls.append(True)
        timings.extra["free_answer"] = {"status": "accepted", "kept": 1}
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())

    monkeypatch.setattr(pipeline, "_free_answer", generate)
    request = AIAnswerRequest(question=_NATURAL_QUESTION)
    first, _, _ = _execute(request)
    second, _, _ = _execute(request)
    assert first.grounded and second.grounded and second.from_cache
    assert len(calls) == 1 and first.answer == second.answer
    source = replace(source, revision=2, content=_SOURCE_TEXT + " Ek bir kaynak cümlesi.")
    third, _, _ = _execute(request)
    assert not third.from_cache and len(calls) == 2


def test_empty_local_search_reaches_official_web_before_no_source_reply(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    from api.ai.official_research import ResearchResult
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name='openrouter', model='cloud-test')
    routing.settings.free_answer_enabled = True
    routing.settings.official_web_research_enabled = True
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)
    monkeypatch.setattr(pipeline, '_retrieve', lambda *a, **kw: [])
    calls = []
    def web(queries, contexts, *, public_scope):
        assert public_scope and not contexts
        calls.append('web')
        return ResearchResult((source,), ({'source': 'mevzuat', 'status': 'document_verified'},))
    monkeypatch.setattr('api.ai.official_research.research_official', web)
    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        assert source in contexts and kwargs['public_web_scope']
        calls.append('writer')
        timings.extra['free_answer'] = {'status': 'accepted', 'kept': 1}
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())
    monkeypatch.setattr(pipeline, '_free_answer', generate)
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.grounded
    assert calls == ['web', 'writer']
    assert timings.extra['official_web'][0]['status'] == 'document_verified'


def test_offline_web_setting_keeps_current_public_local_fast_path(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    routing.settings.free_answer_enabled = True
    routing.settings.official_web_research_enabled = False
    cloud = SimpleNamespace(name='openrouter', model='cloud-test')
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)
    monkeypatch.setattr(pipeline, '_retrieve', lambda *a, **kw: [source])
    seen = []

    def generate(*args, **kwargs):
        seen.append(kwargs['public_web_scope'])
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())

    monkeypatch.setattr(pipeline, '_free_answer', generate)
    response, _, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.grounded and seen == [True]


@pytest.mark.parametrize(
    "part_limit,partial,limit",
    [("none", False, "none"), ("sampled", True, "sampled"), ("failed", True, "failed")],
)
def test_a_part_search_limit_reaches_the_user_summary_with_its_severity(routing, monkeypatch, part_limit, partial, limit):
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name="openrouter", model="cloud-test")
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, "answer_provider", lambda *a, **kw: cloud)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [source])

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        # The outer search was complete; only a planner part's own search was limited (measured 2026-10-30).
        timings.extra["free_answer"] = {"status": "accepted", "kept": 1}
        timings.extra["part_searches"] = [
            {"query": "faiz", "partial": False, "limit": "none", "branches": []},
            {"query": "icra takibi", "partial": part_limit != "none", "limit": part_limit, "branches": []},
        ]
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())

    monkeypatch.setattr(pipeline, "_free_answer", generate)
    response, _, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.grounded
    assert response.search_summary["retrieval_partial"] is partial
    assert response.search_summary["retrieval_limit"] == limit


def test_a_part_search_never_softens_a_graver_outer_limit(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name="openrouter", model="cloud-test")
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, "answer_provider", lambda *a, **kw: cloud)

    def retrieve(*args, diagnostics=None, **kwargs):
        # the outer search lost a lane entirely
        if diagnostics is not None:
            diagnostics.update(partial=True, branches=[{"name": "legislation_m3", "status": "timeout", "seconds": 8.0}])
        return [source]

    monkeypatch.setattr(pipeline, "_retrieve", retrieve)

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        timings.extra["free_answer"] = {"status": "accepted", "kept": 1}
        timings.extra["part_searches"] = [{"query": "faiz", "partial": True, "limit": "sampled", "branches": []}]
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())

    monkeypatch.setattr(pipeline, "_free_answer", generate)
    response, _, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.search_summary["retrieval_limit"] == "failed" and response.search_summary["retrieval_partial"] is True


def test_repeated_named_definition_checks_owner_but_does_not_import_old_topic_or_pay_again(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    from api.ai.verification import VerifiedAnswer
    from tests.test_query_vocabulary import REFERENCE_TEXT
    owner, conversation = uuid4(), uuid4()
    source = legislation_context(content=REFERENCE_TEXT)
    cloud = SimpleNamespace(name="openrouter", model="cloud-test")
    routing.settings.free_answer_enabled = True
    seen, generated = [], []

    async def load(request, user_id):
        assert request.conversation_id == conversation and user_id == owner
        seen.append("owner_checked")
        previous = "Pizza tarifi verir misin?" if len(seen) == 1 else "TÜFE nedir?"
        return (HistoryTurn(previous, "Önceki konu."),), (previous,)

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        assert history == ()
        generated.append(True)
        timings.extra["free_answer"] = {"status": "accepted", "kept": 1}
        return VerifiedAnswer("TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır.", (source,), ())

    monkeypatch.setattr(pipeline, "_load_history", load)
    monkeypatch.setattr(pipeline, "answer_provider", lambda *a, **kw: cloud)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [source])
    monkeypatch.setattr(pipeline, "persist_answer", lambda *a, **kw: (conversation, uuid4()))
    monkeypatch.setattr(pipeline, "_free_answer", generate)
    request = AIAnswerRequest(question="TÜFE nedir?", conversation_id=conversation)
    first, _, _ = _execute(request, owner)
    second, _, _ = _execute(request, owner)
    assert first.grounded and second.grounded and second.from_cache
    assert len(seen) == 2 and len(generated) == 1


@pytest.mark.parametrize("has_sources", [False, True])
def test_plain_definition_can_return_explicit_unverified_general_information(routing, monkeypatch, has_sources):
    cloud = SimpleNamespace(name="openrouter", model="cloud-test")
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, "answer_provider", lambda *a, **kw: cloud)
    source = legislation_context(content="Tüketici fiyat endeksi bir sözleşmede kullanılmıştır.")
    monkeypatch.setattr(pipeline, "_retrieve", lambda *a, **kw: [source] if has_sources else [])
    def failed(*args, **kwargs):
        assert args[-1] is None  # no unverified preview escapes to the client
        return None
    monkeypatch.setattr(pipeline, "_free_answer", failed)
    called = []
    monkeypatch.setattr("api.ai.general_information.generate_definition",
                        lambda p, q: called.append((p, q)) or "TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır.")
    response, _, events = _execute(AIAnswerRequest(question="TÜFE nedir?"))
    assert response.answer_kind == "general_information" and response.grounded is False
    assert response.citations == response.consulted_sources == []
    assert response.provider == "openrouter" and response.model == "cloud-test"
    assert len(called) == 1 and not any(e["stage"] == "draft" for e in events)
    assert events[-1]["stage"] == "done"


@pytest.mark.parametrize("scope", ["project_id", "case_id", "office_project_id", "selected_document_ids", "deep_research"])
def test_general_information_cannot_escape_private_or_deep_research_scope(monkeypatch, scope):
    fields = {} if scope == "deep_research" else {
        scope: [uuid4()] if scope == "selected_document_ids" else uuid4(),
    }
    monkeypatch.setattr("api.ai.general_information.generate_definition", _never("general model in private/deep scope"))
    result = asyncio.run(pipeline._general_definition_fallback(
        AIAnswerRequest(question="TÜFE nedir?", **fields), uuid4(),
        provider=SimpleNamespace(name="openrouter", model="cloud"), local_provider=object(),
        generation_profile="deep_research" if scope == "deep_research" else "default",
        timings=pipeline.PipelineTimings(), started=0, emit=_never("progress"), audit=None,
    ))
    assert result is None


def test_invalid_natural_checker_never_dumps_the_full_source_instead_of_an_answer(routing, monkeypatch):
    from api.ai import explanation, statute_summary
    routing.settings.rag_explanations = True
    monkeypatch.setattr(explanation, "explain_verified_answer", _never("unchecked second paraphrase after synthesis rejection"))
    monkeypatch.setattr(statute_summary, "eligible", _never("partial summary hiding the main rule"))
    provider = _use_actual_synthesis(monkeypatch, routing, responses=[_draft(), _verdict(supported=False)])
    fallback_calls = []
    def exact_fallback(*args, **kwargs):
        fallback_calls.append(kwargs)
        return _SOURCE_TEXT + " [K1]"
    monkeypatch.setattr(pipeline, "generate_grounded_answer", exact_fallback)
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))

    assert len(provider.calls) == 2 and fallback_calls == []
    assert response.grounded is False and response.answer_kind == "insufficient_sources"
    assert _SOURCE_TEXT not in response.answer and _NATURAL_TEXT not in response.answer
    assert response.summary == response.citations == response.consulted_sources == []
    assert response.provider == "application"
    assert "doğrulayamadım" in response.answer
    assert "kaynaklar bulundu" in response.answer
    assert timings.extra["answer_mode"] == "synthesis_unavailable"


def test_failed_natural_checker_does_not_release_an_unsupported_extractive_fallback(routing, monkeypatch):
    _use_actual_synthesis(monkeypatch, routing, responses=[_draft(), _verdict(supported=False)])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", _never("weaker second generation after rejected synthesis"))
    events = []
    response, _ = asyncio.run(pipeline.execute_answer(AIAnswerRequest(question=_NATURAL_QUESTION), None, on_stage=events.append))
    assert response.answer_kind == "insufficient_sources" and not response.grounded
    assert response.citations == [] and "300" not in response.answer
    assert events[-1]["stage"] == "done"
    assert len(answer_cache) == 0


def test_pending_corpus_text_is_never_sent_to_natural_writer_or_checker(routing, monkeypatch):
    pending = replace(court_decision_context(
        chunk_id="00000000-0000-0000-0000-0000000000a1",
        source_id="00000000-0000-0000-0000-0000000000a2",
        content="BEKLEYEN_ARSIV_METNI kullanıcıya veya modele gönderilmemelidir.",
    ), verification="third_party")
    provider = _use_actual_synthesis(monkeypatch, routing, contexts=[pending, legislation_context(content=_SOURCE_TEXT)])
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.grounded and response.answer == _NATURAL_TEXT + " [K1]"
    assert len(provider.calls) == 2
    for call in provider.calls:
        payload = json.loads(call["prompt"])
        assert len(payload["sources"]) == 1
        assert payload["sources"][0]["text"] == _SOURCE_TEXT
        assert "BEKLEYEN_ARSIV_METNI" not in call["prompt"]
    assert all(citation.source_id != pending.source_id for citation in response.citations)
    assert timings.extra["unverified_excluded"] == 1


@pytest.mark.parametrize("field", ["project_id", "case_id", "office_project_id", "selected_document_ids"])
def test_scoped_natural_answers_keep_both_writer_and_checker_local_even_when_cloud_is_enabled(routing, monkeypatch, field):
    routing.settings.cloud_ai_provider = "deepseek"
    private = replace(document_context(content=_SOURCE_TEXT), verification="user_document")
    provider = _use_actual_synthesis(monkeypatch, routing, contexts=[private])
    monkeypatch.setattr(pipeline, "create_cloud_provider", _never("cloud construction for private scope"))
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (uuid4(), uuid4()))
    value = [private.source_id] if field == "selected_document_ids" else uuid4()
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION, **{field: value}), uuid4())

    assert response.grounded is True and response.answer == _NATURAL_TEXT + " [K1]"
    assert response.provider == "ollama" and response.model == "test-natural"
    assert len(provider.calls) == 2 and not provider.responses
    assert response.citations[0].source_type == "document"
    assert response.citations[0].verification == "user_document"
    assert timings.extra["answer_mode"] == "synthesis"


def _clarification_verdict(**overrides):
    return {"claims": [], "coverage_preserved": True, "source_only": True, "clarification_safe": True, **overrides}


def test_confirmed_source_gap_does_not_trigger_article_dump_or_full_search_retry(routing, monkeypatch):
    provider = _use_actual_synthesis(monkeypatch, routing, responses=[
        {"claims": [], "source_gap": True}, _clarification_verdict(),
    ])
    monkeypatch.setattr(pipeline, "try_fast_statute", lambda **kwargs: [legislation_context(content=_SOURCE_TEXT)])
    monkeypatch.setattr(pipeline, "_retrieve", _never("full search recursion after a checked data gap"))
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert response.answer_kind == "insufficient_sources" and not response.grounded
    assert "getirilen kaynaklarda" in response.answer and _SOURCE_TEXT not in response.answer
    assert response.citations == [] and len(provider.calls) == 2
    assert timings.extra["synthesis"] == {"status": "accepted", "reason": "source_gap"}


@pytest.mark.parametrize("question", ["kiraya ne kadar zam yaparım en fazla", "18 bin kira alıom zam ne kadar", "kiramı kaç yapabilirim"])
def test_colloquial_personal_rent_question_can_ask_missing_facts_instead_of_pasting_the_article(routing, monkeypatch, question):
    clarification = "Sözleşmeniz hangi tarihte başladı ve hangi ayda yenileniyor?"
    _use_actual_synthesis(monkeypatch, routing, contexts=[_rent_context()], responses=[
        {"claims": [], "question": clarification}, _clarification_verdict(),
    ])
    response, _, _ = _execute(AIAnswerRequest(question=question))
    assert response.answer_kind == "clarification"
    assert "yenileneceği ay ve yılı" in response.answer and "konut mu" in response.answer
    assert ("mevcut kira tutarını" in response.answer.lower()) == ("18 bin" not in question)
    assert response.summary == response.citations == [] and not response.grounded


def test_question_only_natural_answer_is_safe_clarification_without_extracting_or_recursing(routing, monkeypatch):
    from api.ai import explanation, statute_summary
    clarification = "Tebliğ tarihiniz hangi gün?"
    provider = _use_actual_synthesis(monkeypatch, routing, responses=[
        {"claims": [], "question": clarification}, _clarification_verdict(),
    ])
    source = legislation_context(content=_SOURCE_TEXT)
    # A fast source used to trigger a full-search retry for every grounded=false
    # reply. Safe clarification has no legal finding and must not enter that loop.
    monkeypatch.setattr(pipeline, "try_fast_statute", lambda **kwargs: [source])
    monkeypatch.setattr(pipeline, "_retrieve", _never("full-search recursion for clarification"))
    monkeypatch.setattr(explanation, "explain_verified_answer", _never("legacy clarification explanation"))
    monkeypatch.setattr(statute_summary, "eligible", _never("legacy clarification summary"))
    routing.settings.rag_explanations = True

    owner, executed = uuid4(), []
    @contextmanager
    def authenticated(user_id):
        assert user_id == str(owner)
        yield SimpleNamespace(execute=lambda sql, params: executed.append((sql, params)))
    monkeypatch.setattr(pipeline, "authenticated_database_connection", authenticated)
    monkeypatch.setattr(pipeline, "persist_answer", real_persist_answer)
    monkeypatch.setattr(pipeline, "record_event", lambda *args, **kwargs: None)
    response, timings, events = _execute(AIAnswerRequest(question=_NATURAL_QUESTION), owner)

    assert response.answer == clarification and response.answer_kind == "clarification"
    assert response.grounded is False and response.citations == response.summary == []
    assert response.unverified_markers == [] and response.from_cache is False
    assert response.provider == "ollama" and len(provider.calls) == 2
    assert "fast_statute_fallback" not in timings.extra
    assert timings.extra["answer_mode"] == "synthesis"
    assert events[-1]["stage"] == "done"
    assert events[-1]["result"]["answer_kind"] == "clarification"
    assert events[-1]["result"]["grounded"] is False
    assert len(executed) == 3 and len(answer_cache) == 0
    metadata = executed[2][1][-1].obj
    assert metadata["answer_kind"] == "clarification" and metadata["grounded"] is False
    saved = conversations.build_messages([{
        "id": response.message_id, "role": "assistant", "content": response.answer,
        "created_at": datetime.now(timezone.utc), "model_name": response.model, "metadata": metadata,
    }], [])
    assert saved[0].answer_kind == "clarification" and saved[0].grounded is False


@pytest.mark.parametrize("failed_field", ["clarification_safe", "coverage_preserved", "source_only"])
def test_rejected_question_only_checker_cannot_leak_its_question_into_the_fallback(routing, monkeypatch, failed_field):
    clarification = "Tebliğ tarihiniz hangi gün?"
    provider = _use_actual_synthesis(monkeypatch, routing, responses=[
        {"claims": [], "question": clarification}, _clarification_verdict(**{failed_field: False}),
    ])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", lambda *args, **kwargs: _SOURCE_TEXT + " [K1]")
    response, timings, events = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert len(provider.calls) == 2
    assert response.answer_kind == "insufficient_sources" and response.grounded is False
    assert _SOURCE_TEXT not in response.answer and clarification not in response.answer
    assert clarification not in json.dumps(events, ensure_ascii=False)
    assert timings.extra["answer_mode"] == "synthesis_unavailable"


_RENT_SOURCE_TEXT = (
    "Tarafların yenilenen kira dönemlerinde uygulanacak kira bedeline ilişkin anlaşmaları, "
    "bir önceki kira yılında tüketici fiyat endeksindeki oniki aylık ortalamalara göre "
    "değişim oranını geçmemek koşuluyla geçerlidir."
)


def _rent_context():
    return replace(legislation_context(content=_RENT_SOURCE_TEXT), law_no="6098", article_no="344", law_name="Türk Borçlar Kanunu")


def test_rent_amount_without_user_rate_remains_in_natural_dialogue_instead_of_canned_calculator(routing, monkeypatch):
    clarification = "Sözleşmeniz hangi ayda yenileniyor?"
    provider = _use_actual_synthesis(monkeypatch, routing, contexts=[_rent_context()], responses=[
        {"claims": [], "question": clarification}, _clarification_verdict(),
    ])
    response, timings, _ = _execute(AIAnswerRequest(question="18 bin kira alıyorum, en fazla ne kadar kira artışı yapabilirim?"))
    assert response.provider == "application" and response.model == "dialogue-inputs-v1"
    assert response.answer_kind == "clarification"
    assert "yenileneceği ay ve yılı" in response.answer and "konut mu" in response.answer
    assert "mevcut kira tutarını" not in response.answer.lower()
    assert response.summary == [] and response.grounded is False
    assert len(provider.calls) == 0
    assert timings.extra["missing_inputs"] == ["renewal_period", "property_type"]


def test_explicit_arithmetic_does_not_search_sources_or_call_a_model(routing, monkeypatch):
    monkeypatch.setattr(pipeline, "create_provider", _never("arithmetic model creation"))
    monkeypatch.setattr(pipeline, "_retrieve", _never("arithmetic retrieval"))
    response, _, _ = _execute(AIAnswerRequest(question="10 * 40000 kaç eder?"))
    assert response.answer == "400.000"
    assert response.provider == "application" and not response.grounded
    assert response.citations == []


def test_arithmetic_still_checks_conversation_ownership_before_reply(routing, monkeypatch):
    async def denied(*args):
        raise HTTPException(404, "Sohbet bulunamadı")
    monkeypatch.setattr(pipeline, "_load_history", denied)
    with pytest.raises(HTTPException) as error:
        _execute(AIAnswerRequest(question="2+2", conversation_id=uuid4()), uuid4())
    assert error.value.status_code == 404


def test_follow_up_keeps_original_event_and_only_asks_for_still_missing_inputs(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    original = "Ben 10 sene çalıştım çıkarıldım ne kadar toplu para alırım?"
    source = legislation_context(content="İşçinin işe başladığı tarihten itibaren her tam yıl için ücreti tutarında kıdem tazminatı ödenir.")
    provider = _use_actual_synthesis(monkeypatch, routing, contexts=[source], responses=[])
    async def loaded(*args):
        return (HistoryTurn(original, "Son brüt ücretinizi paylaşır mısınız?", "clarification"),), (original,)
    monkeypatch.setattr(pipeline, "_load_history", loaded)
    monkeypatch.setattr(pipeline, "standalone_question", _never("redundant input reply rewrite"))
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (uuid4(), uuid4()))
    response, _, _ = _execute(AIAnswerRequest(question="Son brüt ücretim 40000 TL", conversation_id=uuid4()), uuid4())
    assert response.answer_kind == "clarification" and "tarihlerinizi" in response.answer
    assert "brüt ücretinizi" not in response.answer and provider.calls == []


def test_exact_user_screenshot_cannot_end_in_the_generic_fallback_or_invent_a_payout(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    first = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
    details = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
    last = "küçülmeye gittiler çıkardılar"
    source = replace(legislation_context(content="İşçi kıdem tazminatı bakımından bu hükümlere tabidir."),
                     effective_from=None, effective_to=None)
    _use_actual_synthesis(monkeypatch, routing, contexts=[source], responses=["not JSON"])
    async def loaded(*args):
        return (HistoryTurn(first,"Bilgileri paylaşır mısınız?","clarification"),
                HistoryTurn(details,"İşten ayrılma nedeninizi paylaşır mısınız?","clarification")), (first,details)
    monkeypatch.setattr(pipeline,"_load_history",loaded)
    monkeypatch.setattr(pipeline,"try_fast_statute",lambda **kwargs: [])
    monkeypatch.setattr(pipeline,"standalone_question",_never("factual reply model rewrite"))
    seen = []
    def retrieve(*args, **kwargs):
        seen.append(kwargs["question"])
        return [source]
    monkeypatch.setattr(pipeline,"_retrieve",retrieve)
    monkeypatch.setattr(pipeline,"persist_answer",lambda *args,**kwargs:(uuid4(),uuid4()))
    # A malformed writer/rejected meaning must still preserve the user's facts
    # and exact missing temporal proof rather than a generic dead end.
    from api.ai import synthesis
    monkeypatch.setattr(synthesis,"synthesize_answer",lambda *args,**kwargs: None)
    response, _, _ = _execute(AIAnswerRequest(question=last,conversation_id=uuid4()),uuid4())
    assert "10 yıl 4 ay 1 gün" in response.answer and "brüt ücret 50.000" in response.answer
    assert "13.03.2016 için" in response.answer and "500.000" not in response.answer
    assert "İlgili kaynaklar bulundu ancak" not in response.answer
    assert all("50000" not in query and "2005" not in query and "2016" not in query for query in seen)
    assert not response.grounded and response.citations == []


def test_additional_event_questions_do_not_hide_an_unverified_historical_basis(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    first = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
    details = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
    source = replace(legislation_context(content="İşçi ücret ve tazminat bakımından bu hükümlere tabidir."),
                     effective_from=None,effective_to=None)
    _use_actual_synthesis(monkeypatch,routing,contexts=[source],responses=[
        {"claims":[],"question":"İşyerinde kaç kişi çalışıyordu?"}, _clarification_verdict()])
    async def loaded(*args):
        return (HistoryTurn(details,"Ayrılma nedeninizi paylaşır mısınız?","clarification"),),(first,details)
    monkeypatch.setattr(pipeline,"_load_history",loaded)
    response, _, _ = _execute(AIAnswerRequest(question="küçülmeye gittiler çıkardılar"))
    assert response.answer_kind == "insufficient_sources" and "mevzuat sürümü" in response.answer
    assert "İşyerinde kaç kişi" not in response.answer and "50.000" in response.answer


def test_completed_personal_calculation_never_falls_back_to_dumping_a_statute(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    from api.ai import synthesis
    first = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
    details = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
    source = replace(legislation_context(content="İşçi kıdem tazminatı bakımından bu hükümlere tabidir."),
                     effective_from=None,effective_to=None)
    _use_actual_synthesis(monkeypatch,routing,contexts=[source])
    async def loaded(*args):
        return (HistoryTurn(details,"Ayrılma nedeni?","clarification"),),(first,details)
    monkeypatch.setattr(pipeline,"_load_history",loaded)
    def failed(*args,**kwargs):
        kwargs["diagnostics"].update(status="fallback",reason="dropped_coverage")
        return None
    monkeypatch.setattr(synthesis,"synthesize_answer",failed)
    monkeypatch.setattr(pipeline,"generate_grounded_answer",_never("article dump after personal answer rejection"))
    response,_,_ = _execute(AIAnswerRequest(question="küçülmeye gittiler çıkardılar"))
    assert response.answer_kind == "insufficient_sources" and "10 yıl 4 ay 1 gün" in response.answer
    assert source.content not in response.answer and len(response.answer) < 750


def test_missing_historical_proof_can_explain_current_reference_without_claiming_a_payout(routing, monkeypatch):
    from api.ai import synthesis
    from api.ai.event_lookup import lookup_event_basis
    from api.ai.dialogue import outcome_search_query
    from api.ai.rag import HistoryTurn
    from api.ai.verification import VerifiedAnswer
    first = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
    details = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
    last = "küçülmeye gittiler çıkardılar"
    source = replace(legislation_context(content="Bildirim şartına uymayan taraf tazminat ödemek zorundadır."),
                     law_no="4857", article_no="17", effective_from=None, effective_to=None)
    temporal = lookup_event_basis(last, outcome_search_query(last, prior_questions=[first,details]),
        prior_questions=[first,details], loader=lambda *args: [])
    monkeypatch.setattr(pipeline,"lookup_event_basis",lambda *args,**kwargs:temporal)
    monkeypatch.setattr(pipeline,"load_current_event_reference",lambda *args:[source])
    monkeypatch.setattr(pipeline,"_retrieve",_never("unbounded historical retrieval for reference-only explanation"))
    async def loaded(*args):
        return (HistoryTurn(details,"Ayrılma nedeni?","clarification"),),(first,details)
    monkeypatch.setattr(pipeline,"_load_history",loaded)
    def explain(*args,**kwargs):
        assert kwargs["event_basis_complete"] is False
        assert kwargs["contexts"] == [source]
        return VerifiedAnswer(text=source.content + " [K1]",contexts=(source,),unverified_markers=())
    monkeypatch.setattr(synthesis,"synthesize_answer",explain)
    response,timings,_ = _execute(AIAnswerRequest(question=last))
    assert response.grounded and len(response.citations)==1
    assert "kesin bir hak veya tutar tespiti değildir" in response.answer
    assert source.content in response.answer and "10 yıl 4 ay 1 gün" in response.answer
    assert "500.000" not in response.answer and timings.extra["event_reference_only"] is True


def test_explicit_rent_amount_and_rate_do_not_require_a_statute_or_model(routing, monkeypatch):
    monkeypatch.setattr(pipeline, "_retrieve", _never("retrieval for nonlegal percentage arithmetic"))
    monkeypatch.setattr(pipeline, "create_provider", _never("model for nonlegal percentage arithmetic"))
    response, _, _ = _execute(AIAnswerRequest(question="Örnek kira artışı: 18 bin kira için %20 artış ne kadar olur?"))
    assert response.provider == "application" and response.model == "declared-percentage-v1"
    assert response.grounded is False and response.answer_kind == "conversation"
    assert response.citations == [] and response.summary == []
    assert "21.600" in response.answer and "3.600" in response.answer
    assert "MADDE" not in response.answer and "TL" not in response.answer


def test_percentage_followup_checks_ownership_before_reusing_a_user_amount(routing, monkeypatch):
    async def denied(*args):
        raise HTTPException(404, "Sohbet bulunamadı")
    monkeypatch.setattr(pipeline, "_load_history", denied)
    with pytest.raises(HTTPException) as error:
        _execute(AIAnswerRequest(question="%20 artışla kira kaç olur?", conversation_id=uuid4()), uuid4())
    assert error.value.status_code == 404


def test_ambiguous_rent_ceiling_asks_only_missing_scope_instead_of_dumping_all_rules(routing, monkeypatch):
    monkeypatch.setattr(pipeline,"create_provider",_never("model for missing neutral rent scope"))
    response,_,_ = _execute(AIAnswerRequest(question="Kira artışı en fazla ne kadar olabilir?"))
    assert response.answer_kind == "clarification" and not response.grounded
    assert "ay ve yılı" in response.answer and "konut mu" in response.answer
    assert "tutarını" not in response.answer and response.citations == []


def test_known_renewal_month_and_property_are_not_asked_again(routing, monkeypatch):
    from api.ai.rag import HistoryTurn
    first = "Kira artışı en fazla ne kadar olabilir?"
    async def loaded(*args):
        return (HistoryTurn(first,"Dönem ve kira türünü paylaşır mısınız?","clarification"),),(first,)
    monkeypatch.setattr(pipeline,"_load_history",loaded)
    monkeypatch.setattr(pipeline,"create_provider",_never("model for one missing year"))
    response,_,_ = _execute(AIAnswerRequest(question="Konut, her yıl eylül ayında yenileniyor, kira 20000 TL."))
    assert response.answer_kind == "clarification"
    assert "hangi yılda" in response.answer
    assert "ay ve yılı" not in response.answer and "konut mu" not in response.answer


def test_percentage_reply_does_not_read_amounts_from_private_documents(routing, monkeypatch):
    def retrieve(*args, **kwargs):
        routing.calls.append("retrieval")
        return []
    monkeypatch.setattr(pipeline, "_retrieve", retrieve)
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (uuid4(), uuid4()))
    response, _, _ = _execute(AIAnswerRequest(question="%20 artışla kira kaç olur?", selected_document_ids=[uuid4()]),uuid4())
    assert response.model != "declared-percentage-v1" and "retrieval" in routing.calls


def test_a_rejected_natural_answer_does_not_dump_unsolicited_article_text(routing, monkeypatch):
    inexact = {"claims": [{"text": _NATURAL_TEXT, "evidence": [{"source": 1, "quote": "Süre tebliğden başlar."}]}],
               "question": None}
    _use_actual_synthesis(monkeypatch, routing, responses=[inexact, inexact])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", _never("unsolicited quote fallback"))
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert timings.extra["synthesis"]["reason"] == "evidence"
    assert timings.extra["answer_mode"] == "synthesis_unavailable"
    assert not response.grounded and response.answer_kind == "insufficient_sources"
    assert response.citations == [] and _SOURCE_TEXT not in response.answer
    assert len(answer_cache) == 0


def test_rejected_source_gap_does_not_bypass_natural_coverage_checks(routing, monkeypatch):
    disagree = {"claims": [], "coverage_preserved": False, "source_only": True, "clarification_safe": False}
    _use_actual_synthesis(monkeypatch, routing, responses=[{"claims": [], "source_gap": True}, disagree])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", _never("coverage-erasing fallback"))
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    assert timings.extra["synthesis"]["reason"] == "unconfirmed_source_gap"
    assert timings.extra["answer_mode"] == "synthesis_unavailable" and not response.grounded


def test_explicit_request_for_verbatim_text_can_still_use_verified_quotation(routing, monkeypatch):
    inexact = {"claims": [{"text": _NATURAL_TEXT, "evidence": [{"source": 1, "quote": "Süre tebliğden başlar."}]}], "question": None}
    _use_actual_synthesis(monkeypatch, routing, responses=[inexact, inexact])
    monkeypatch.setattr(pipeline, "generate_grounded_answer", lambda *args, **kwargs: _SOURCE_TEXT + " [K1]")
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION + " Kaynağı aynen göster."))
    assert timings.extra["answer_mode"] == "synthesis_then_quotes"
    assert response.grounded and _SOURCE_TEXT in response.answer


def test_dynamic_research_uses_existing_scoped_retrieval_and_preserves_as_of(routing, monkeypatch):
    from datetime import date
    from api.ai import research_plan
    aspects = (research_plan.Aspect("A1", "Koşullar", "talep koşulları"),
               research_plan.Aspect("A2", "Başvuru", "başvuru yolları"))
    cloud = SimpleNamespace(name="openrouter", model="fixture", generate=_never("unplanned generation"))
    monkeypatch.setattr(pipeline, "answer_provider", lambda *args, **kwargs: cloud)
    monkeypatch.setattr(research_plan, "make_plan", lambda *args, **kwargs: aspects)
    queries = []
    def retrieve(request, **kwargs):
        queries.append((kwargs["question"], request.as_of, kwargs["user_id"]))
        return []
    monkeypatch.setattr(pipeline, "_retrieve", retrieve)
    requested_date = date(2020, 1, 1)
    _, timing, _ = _execute(AIAnswerRequest(question="İşçinin hakları nelerdir?", as_of=requested_date))
    assert {q for q, _, _ in queries} >= {a.query for a in aspects}
    assert all(d == requested_date and u is None for _, d, u in queries)
    assert timing.extra["research_plan"]["searched"] == 2
    assert not {"pause", "unload", "resume"} & set(routing.calls)


@pytest.mark.parametrize("scope", ["project_id", "case_id", "office_project_id", "selected_document_ids"])
def test_private_scope_never_calls_cloud_research_planner_even_if_provider_routing_regresses(routing, monkeypatch, scope):
    from api.ai import research_plan
    cloud = SimpleNamespace(name="openrouter", model="fixture", generate=_never("private cloud generation"))
    monkeypatch.setattr(pipeline, "answer_provider", lambda *args, **kwargs: cloud)
    monkeypatch.setattr(research_plan, "make_plan", _never("private cloud planning"))
    monkeypatch.setattr(pipeline, "persist_answer", lambda *args, **kwargs: (uuid4(), uuid4()))
    async def scoped_history(*args):
        return (), ()
    monkeypatch.setattr(pipeline, "_load_history", scoped_history)
    value = [uuid4()] if scope == "selected_document_ids" else uuid4()
    response, timing, _ = _execute(AIAnswerRequest(question="Bu işten çıkarılmada haklarım nelerdir?", **{scope:value}), uuid4())
    assert "research_plan" not in timing.extra and not response.grounded


def test_invalid_planner_output_keeps_the_existing_retrieval_path(routing, monkeypatch):
    cloud = SimpleNamespace(name="openrouter", model="fixture", generate=lambda **kwargs: "not a plan")
    monkeypatch.setattr(pipeline, "answer_provider", lambda *args, **kwargs: cloud)
    response, timing, _ = _execute(AIAnswerRequest(question="İşçinin hakları nelerdir?"))
    assert "retrieval" in routing.calls
    assert timing.extra["research_plan"]["status"] == "unavailable"
    assert response.answer_kind == "insufficient_sources"


def test_a_precomputed_answer_is_served_before_any_search_or_model_call(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    cloud = SimpleNamespace(name="cloud", model="cloud-test", generate=_never("model generation"))
    routing.settings.free_answer_enabled = True
    routing.settings.warm_answer_cache_enabled = True
    monkeypatch.setattr(pipeline, "_answer_providers", lambda settings, request, profile: (routing.provider, cloud))
    warm = VerifiedAnswer(text="Önceden hazırlanmış kaynaklı cevap.", contexts=(legislation_context(),), unverified_markers=())
    asked = []
    monkeypatch.setattr(pipeline, "_warm_cache_lookup", lambda question: asked.append(question) or warm)

    response, timings, events = _execute(AIAnswerRequest(question="Kıdem tazminatı nedir?"))

    assert response.answer == "Önceden hazırlanmış kaynaklı cevap." and response.from_cache and response.grounded
    assert timings.extra["warm_cache"] is True and asked == ["Kıdem tazminatı nedir?"]
    assert "retrieval" not in routing.calls and "fast_lookup" not in routing.calls
    assert events[-1]["stage"] == "done" and len(response.citations) == 1


def test_a_scoped_question_never_reads_the_precomputed_answers(routing, monkeypatch):
    import uuid
    cloud = SimpleNamespace(name="cloud", model="cloud-test", generate=_never("model generation"))
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, "_answer_providers", lambda settings, request, profile: (routing.provider, cloud))
    monkeypatch.setattr(pipeline, "_warm_cache_lookup", _never("precomputed answer lookup"))
    request = AIAnswerRequest(question="Kıdem tazminatı nedir?", case_id=uuid.uuid4())
    assert pipeline._warm_cache_eligible(request, routing.settings, cloud, routing.provider, (), "default") is False


def test_the_stored_answers_do_not_answer_for_the_warmup_script_that_is_generating_them(routing, monkeypatch):
    from api.ai import warm_cache
    cloud = SimpleNamespace(name="cloud", model="cloud-test", generate=_never("model generation"))
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, "_answer_providers", lambda settings, request, profile: (routing.provider, cloud))
    monkeypatch.setattr(pipeline, "_warm_cache_lookup", _never("stored answer read during warm-up"))
    token = warm_cache.collector.set(lambda *args: None)
    try:
        # the stored-answer read is skipped; the normal pipeline then needs sources, which this fake search does not have
        try:
            _execute(AIAnswerRequest(question="Kıdem tazminatı nedir?"))
        except pytest.fail.Exception:
            raise
        except Exception:  # noqa: BLE001 - what happens after the skipped read is not what this test is about
            pass
    finally:
        warm_cache.collector.reset(token)


def test_an_unmatched_named_article_gets_the_article_answer_not_the_generic_one(routing):
    routing.settings.free_answer_enabled = True
    response, _, _ = _execute(AIAnswerRequest(
        question="4857 sayılı İş Kanunu'nun 999. maddesi neyi düzenliyor? Böyle bir madde yoksa açıkça belirt ve madde uydurma."))
    assert response.answer_kind == "insufficient_sources" and response.grounded is False
    assert "999. maddesini" in response.answer
    assert "belgeyi seçebilir" not in response.answer


@pytest.mark.parametrize("changes, expected", [
    ({}, True),
    ({"natural_mode": False}, False),
    ({"generation_profile": "deep_research"}, False),
    ({"cloud_provider": False}, False),
    ({"force_full": True}, False),
    ({"has_seed": True}, False),
])
def test_the_whole_question_search_skips_vector_lanes_only_for_general_cloud_chat(changes, expected):
    arguments = dict(natural_mode=True, generation_profile="default", cloud_provider=True, force_full=False, has_seed=False)
    assert pipeline._seed_search_only(AIAnswerRequest(question="Zamanaşımı nasıl kesilir?"), **{**arguments, **changes}) is expected


@pytest.mark.parametrize("field", ["project_id", "case_id", "office_project_id", "selected_document_ids"])
def test_private_scopes_and_historical_questions_keep_the_full_search(field):
    value = [uuid4()] if field == "selected_document_ids" else uuid4()
    arguments = dict(natural_mode=True, generation_profile="default", cloud_provider=True, force_full=False, has_seed=False)
    assert pipeline._seed_search_only(AIAnswerRequest(question="soru", **{field: value}), **arguments) is False
    assert pipeline._seed_search_only(AIAnswerRequest(question="soru", as_of="2020-01-01"), **arguments) is False


def test_an_empty_word_and_statute_seed_falls_back_to_the_full_vector_search(routing, monkeypatch):
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name='openrouter', model='cloud-test')
    routing.settings.free_answer_enabled = True
    routing.settings.rag_query_embedding = True
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)
    embedded = []

    async def shared(question):
        embedded.append("shared")
        return [0.1]

    async def legislation(question):
        embedded.append("legislation")
        return [0.2]

    seen = []

    def retrieve(*a, **kwargs):
        seen.append(kwargs.get("query_embedding"))
        return [source] if kwargs.get("query_embedding") else []

    monkeypatch.setattr(pipeline, '_embed_question', shared)
    monkeypatch.setattr(pipeline, '_embed_legislation_question', legislation)
    monkeypatch.setattr(pipeline, '_retrieve', retrieve)

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        timings.extra['free_answer'] = {'status': 'accepted', 'kept': 1}
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())
    monkeypatch.setattr(pipeline, '_free_answer', generate)
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    # the seed search ran without vectors first; only its empty result paid for the question's vectors and the full search
    assert seen == [None, [0.1]] and sorted(embedded) == ["legislation", "shared"]
    assert timings.extra['seed_search_lexical_only'] is False and response.grounded


def test_a_database_error_in_the_seed_search_does_not_fail_the_general_chat_request(routing, monkeypatch):
    import psycopg
    from api.ai.verification import VerifiedAnswer
    source = legislation_context(content=_SOURCE_TEXT)
    cloud = SimpleNamespace(name='openrouter', model='cloud-test')
    routing.settings.free_answer_enabled = True
    routing.settings.rag_query_embedding = False
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)

    def refused(*a, **kwargs):
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(pipeline, '_retrieve', refused)
    seen = {}

    def generate(provider, question, contexts, history, timings, checker, on_draft=None, **kwargs):
        seen['contexts'] = list(contexts)
        timings.extra['free_answer'] = {'status': 'accepted', 'kept': 1}
        return VerifiedAnswer(_NATURAL_TEXT, (source,), ())

    monkeypatch.setattr(pipeline, '_free_answer', generate)
    response, timings, _ = _execute(AIAnswerRequest(question=_NATURAL_QUESTION))
    # the part searches (inside `_free_answer`) got their chance: the answer exists and the research is flagged incomplete
    assert response.grounded and seen['contexts'] == []
    assert timings.extra['retrieval']['partial'] is True


def test_the_same_database_error_still_fails_a_scoped_or_non_general_request(routing, monkeypatch):
    import psycopg
    cloud = SimpleNamespace(name='openrouter', model='cloud-test')
    routing.settings.free_answer_enabled = True
    monkeypatch.setattr(pipeline, 'answer_provider', lambda *a, **kw: cloud)

    def refused(*a, **kwargs):
        raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(pipeline, '_retrieve', refused)
    with pytest.raises(HTTPException) as error:
        _execute(AIAnswerRequest(question=_NATURAL_QUESTION, as_of="2020-01-01"))
    assert error.value.status_code == 503
