"""Cevapta alıntılanmayan ama incelenen doğrulanmış kaynaklar listelenir; yalnız doğrulanmışlar."""

from __future__ import annotations

import asyncio
import psycopg
import pytest
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

from api.ai import pipeline
from api.ai.pipeline import CONSULTED_SOURCE_LIMIT, _response_from_verified, consulted_sources
from api.ai.verification import VerifiedAnswer
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context, document_context, legislation_context


def _decision(n: int, *, verification: str = "official", content: str = "Karar metni örneği."):
    return replace(
        court_decision_context(
            chunk_id=f"00000000-0000-0000-0000-{n:012d}",
            source_id=f"00000000-0000-0000-0001-{n:012d}",
            content=content,
        ),
        verification=verification,
    )


def _answer(*cited, text="Cevap [K1]."):
    return VerifiedAnswer(text=text, contexts=tuple(cited), unverified_markers=())


def test_uncited_verified_sources_are_listed_with_their_own_markers():
    pool = [_decision(1), _decision(2), _decision(3)]
    listed = consulted_sources(_answer(pool[0]), pool)
    assert [item.marker for item in listed] == ["I1", "I2"]
    assert [item.source_id for item in listed] == [pool[1].source_id, pool[2].source_id]
    assert all(item.verification == "official" for item in listed)


def test_a_cited_source_and_its_other_chunks_are_never_repeated():
    cited = _decision(1)
    sibling_chunk = replace(_decision(9), source_id=cited.source_id)
    listed = consulted_sources(_answer(cited), [cited, sibling_chunk, _decision(2)])
    assert [item.source_id for item in listed] == [_decision(2).source_id]


def test_unverified_third_party_records_never_appear():
    pool = [_decision(1), _decision(2, verification="third_party"), _decision(3)]
    listed = consulted_sources(_answer(pool[0]), pool)
    assert [item.source_id for item in listed] == [pool[2].source_id]
    assert all(item.verification != "third_party" for item in listed)


def test_user_documents_are_listed_as_such_and_one_source_appears_once():
    document = replace(document_context(content="Aylık kira bedeli 25.000 TL'dir."), verification="user_document")
    duplicate = replace(document, chunk_id=UUID("00000000-0000-0000-0000-0000000000aa"))
    listed = consulted_sources(_answer(_decision(1)), [_decision(1), document, duplicate])
    assert len(listed) == 1 and listed[0].source_type == "document"
    assert listed[0].verification == "user_document"


def test_the_list_is_capped():
    pool = [_decision(n) for n in range(1, 30)]
    assert len(consulted_sources(_answer(pool[0]), pool)) == CONSULTED_SOURCE_LIMIT


def test_excerpt_is_a_bounded_passage_not_the_whole_text():
    long_text = "Uzun karar gerekçesi. " * 100
    listed = consulted_sources(_answer(_decision(1)), [_decision(1), _decision(2, content=long_text)])
    assert 0 < len(listed[0].excerpt) <= 500


def test_nothing_is_listed_when_the_answer_could_not_be_grounded():
    pool = [_decision(1), _decision(2)]
    insufficient = VerifiedAnswer(text="Yeterli bilgi bulunmuyor.", contexts=(), unverified_markers=())
    assert consulted_sources(insufficient, pool) == []
    ungrounded = VerifiedAnswer(text="x [K1]", contexts=(pool[0],), unverified_markers=("K9",))
    assert consulted_sources(ungrounded, pool) == []


def test_response_carries_the_list_and_the_cited_sources_unchanged():
    pool = [_decision(1), _decision(2), legislation_context()]
    provider = SimpleNamespace(name="ollama", model="m")
    response = _response_from_verified(
        AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"),
        _answer(pool[0]),
        provider=provider,
        conversation_id=None,
        message_id=None,
        from_cache=False,
        consulted=pool,
    )
    assert [c.marker for c in response.citations] == ["K1"]
    assert [c.marker for c in response.consulted_sources] == ["I1", "I2"]
    dumped = response.model_dump(mode="json")
    assert len(dumped["consulted_sources"]) == 2


def test_response_without_consulted_contexts_has_an_empty_list():
    response = _response_from_verified(
        AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"),
        _answer(_decision(1)),
        provider=SimpleNamespace(name="ollama", model="m"),
        conversation_id=None,
        message_id=None,
        from_cache=False,
    )
    assert response.consulted_sources == []


# --- soğuk önbellekte ilk arama: bir kez yeniden denenir -------------------------------------



def _run(coro):
    return asyncio.run(coro)


def test_a_cold_cache_timeout_is_retried_once_and_the_second_try_is_used(monkeypatch):
    calls = []

    def flaky(request, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")
        return ["sonuç"]

    monkeypatch.setattr(pipeline, "_retrieve", flaky)
    assert _run(pipeline._retrieve_with_warm_retry(object(), top_k=3)) == ["sonuç"]
    assert len(calls) == 2


def test_a_second_timeout_is_a_real_failure(monkeypatch):
    calls = []

    def always(request, **kwargs):
        calls.append(1)
        raise psycopg.errors.QueryCanceled("zaman aşımı")

    monkeypatch.setattr(pipeline, "_retrieve", always)
    with pytest.raises(psycopg.errors.QueryCanceled):
        _run(pipeline._retrieve_with_warm_retry(object()))
    assert len(calls) == 2  # sonsuz döngü yok


def test_other_database_errors_are_not_retried(monkeypatch):
    calls = []

    def broken(request, **kwargs):
        calls.append(1)
        raise psycopg.OperationalError("bağlantı koptu")

    monkeypatch.setattr(pipeline, "_retrieve", broken)
    with pytest.raises(psycopg.OperationalError):
        _run(pipeline._retrieve_with_warm_retry(object()))
    assert len(calls) == 1
