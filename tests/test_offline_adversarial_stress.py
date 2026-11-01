"""Deterministic adversarial/property/concurrency tests: no models, no DB."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
import random
import sys
from uuid import UUID

import pytest

from api.ai.cache import AnswerCache, answer_cache_key, source_fingerprint, restore_verified_natural_answer
from api.ai.conversation_intent import out_of_scope_reply
from api.ai.general_information import generate_definition
from api.ai.pipeline import _generation_slot
from api.ai.query_vocabulary import expand_search_terms
from api.ai.retrieval import question_law_numbers, question_article_numbers
from api.ai.synthesis import _fully_approved_ids
from api.ai.verification import VerifiedAnswer
from tests.factories import legislation_context


def test_randomized_explicit_law_article_pairs_do_not_confuse_articles_with_laws():
    rng = random.Random(20261026)
    for _ in range(2000):
        law = str(rng.randint(3000, 9999))
        article = str(rng.randint(1, 999))
        question = f"{law} sayılı Kanun madde {article} neyi düzenler?"
        assert question_law_numbers(question) == (law,)
        assert question_article_numbers(question) == (article,)


def test_query_expansion_is_idempotent_and_never_expands_a_word_interior():
    rng = random.Random(26)
    terms = ["TÜFE", "SGK", "KVKK", "HMK", "TCK", "ÜFE", "KDV"]
    for _ in range(2000):
        term = rng.choice(terms)
        q = f"({term}) nedir?"
        assert expand_search_terms(expand_search_terms(q)) == expand_search_terms(q)
        word = "x" + term + "x"
        assert expand_search_terms(word) == word.lower()


def test_cache_has_no_cross_user_key_collision_and_remains_bounded_under_threads():
    cache = AnswerCache(maxsize=64)
    def run(worker):
        for index in range(1000):
            key = answer_cache_key(question=f"question {index}", project_id=None, as_of=None,
                                   model="fixture", fingerprint="public", user_id=UUID(int=worker+1))
            cache.put(key, {"owner": worker})
            hit = cache.get(key)
            assert hit is None or hit["owner"] == worker
        return True
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(run, range(4)))
    assert len(cache) <= 64


def test_any_modified_evidence_invalidates_cached_proof():
    source = legislation_context()
    payload = {"_verified_natural_answer": VerifiedAnswer("Verified prose.", (source,), ())}
    for i in range(500):
        changed = replace(source, content=source.content + str(i))
        assert source_fingerprint([source]) != source_fingerprint([changed])
        assert restore_verified_natural_answer(payload, [changed]) is None


def test_1000_cloud_tasks_use_at_most_four_slots_without_model_calls():
    async def run():
        local, cloud = object(), object()
        active = peak = completed = 0
        async def one():
            nonlocal active, peak, completed
            async with _generation_slot(cloud, local):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0)
                active -= 1
                completed += 1
        await asyncio.wait_for(asyncio.gather(*(one() for _ in range(1000))), timeout=15)
        assert completed == 1000 and peak <= 4 and active == 0
    asyncio.run(run())


def test_cancelling_100_of_300_waiters_does_not_leak_generation_slots():
    async def run():
        local, cloud = object(), object()
        gate = _generation_slot(cloud, local)
        for _ in range(4):
            await gate.acquire()
        async def one():
            async with _generation_slot(cloud, local):
                await asyncio.sleep(0)
                return True
        tasks = [asyncio.create_task(one()) for _ in range(300)]
        await asyncio.sleep(0)
        for task in tasks[::3]:
            task.cancel()
        for _ in range(4):
            gate.release()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)
        assert sum(isinstance(item, asyncio.CancelledError) for item in results) == 100
        assert sum(item is True for item in results) == 200
        for _ in range(4):
            await asyncio.wait_for(gate.acquire(), timeout=0.5)
        for _ in range(4):
            gate.release()
    asyncio.run(run())


def test_500_oversized_request_payloads_are_rejected_before_generation():
    from pydantic import ValidationError
    from api.schemas import AIAnswerRequest
    for length in range(2001, 2501):
        with pytest.raises(ValidationError):
            AIAnswerRequest(question="x" * length)
    with pytest.raises(ValidationError):
        AIAnswerRequest(question="   ")
    assert len(AIAnswerRequest(question="x" * 2000).question) == 2000


@pytest.mark.parametrize("question", [
    "Pizza siparişim gelmedi, paramı nasıl alırım?",
    "Pizza tarifi ver; ayrıca işten çıkarılma haklarımı açıkla.",
    "Pizza tarifini izinsiz yayımladılar, dava açabilir miyim?",
    "Bu nedir?", "Peki bunun süresi?", "Evet", "Hayır",
])
def test_nonlegal_shortcut_never_swallows_legal_or_ambiguous_followups(question):
    assert out_of_scope_reply(question) is None


@pytest.mark.parametrize("raw_claims", [
    [{"id": 1, "supported": True, "relevant": True, "scope_preserved": True}] * 2,
    [{"id": True, "supported": True, "relevant": True, "scope_preserved": True}],
    [{"id": 0, "supported": True, "relevant": True, "scope_preserved": True}],
    [{"id": 1, "supported": "true", "relevant": True, "scope_preserved": True}],
])
def test_malformed_checker_verdict_can_never_approve_claims(raw_claims):
    raw = json.dumps(dict(claims=raw_claims, coverage_preserved=True,
                          source_only=True, clarification_safe=True))
    assert not _fully_approved_ids(raw, len(raw_claims))


@pytest.mark.parametrize("answer", [
    "İşten çıkarılan her işçi kıdem tazminatını hak eder.",
    "İşverenin sözleşmeyi bitirmesi kıdem tazminatını her zaman doğurur.",
])
def test_general_definition_cannot_be_replaced_by_an_unconditional_legal_result(answer):
    class Provider:
        def generate(self, **kwargs):
            return json.dumps({"answer": answer}, ensure_ascii=False)
    assert generate_definition(Provider(), "TÜFE nedir?") is None


@pytest.mark.skipif(os.getenv("NHR_OFFLINE_AUDIT") != "1", reason="Explicit network-barrier audit only")
def test_real_network_audit_event_is_blocked_before_any_connection():
    with pytest.raises(OSError, match="OFFLINE_AUDIT"):
        sys.audit("socket.connect", object(), ("127.0.0.1", 9))
