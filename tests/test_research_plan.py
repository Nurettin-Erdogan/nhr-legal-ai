"""Plans are untrusted search hints, never authority or permission to use tools."""
import asyncio
from dataclasses import replace
import json
from uuid import UUID

import pytest

from api.ai import research_plan as rp
from api.ai.synthesis import synthesize_answer
from tests.factories import legislation_context
from tests.test_synthesis import Provider, approved


def article(n, text):
    return replace(legislation_context(content=text), chunk_id=UUID(int=n), source_id=UUID(int=n),
                   law_no="9999", article_no=str(n))


def evidence(*sources):
    return rp.ResearchEvidence(tuple(rp.Aspect(f"A{i}", f"Araştırma konusu {chr(64+i)}", "hukuki arama konusu")
                                     for i in range(1, len(sources)+1)),
        tuple((f"A{i}", frozenset({str(c.chunk_id)})) for i, c in enumerate(sources, 1)))


def test_plan_has_only_queries_not_legal_facts_source_ids_or_tools():
    result = rp.make_plan(Provider({"aspects": [{"label": "Talep koşulları", "query": "fesih işçi talepleri koşulları"}]}), "İşten çıkarıldım haklarım neler?")
    assert result == (rp.Aspect("A1", "Talep koşulları", "fesih işçi talepleri koşulları"),)


@pytest.mark.parametrize("raw", [
    {"aspects": []}, {"aspects": [{}]*6}, {"aspects": [], "answer": "hak kazanır"},
    {"aspects": [{"label": "Kural", "query": "4857 madde 17"}]},
    {"aspects": [{"label": "Kural", "query": "https://example.org"}]},
    {"aspects": [{"label": "Kural", "query": "DROP TABLE legal_sources"}]},
    {"aspects": [{"label": "Kural", "query": "araştır", "source_id": "invented"}]},
    '{"aspects":[],"aspects":[{"label":"Kural","query":"hukuki koşullar"}]}',
    "not json",
])
def test_malformed_or_tool_like_plan_is_not_used(raw):
    diagnostic = {}
    assert rp.make_plan(Provider(raw), "Soru", diagnostics=diagnostic) == ()
    assert diagnostic == {"status": "unavailable", "aspects": 0}


def test_failed_search_is_partial_and_pending_text_is_never_evidence():
    ready = article(1, "Başvuru süresi tebliğden başlar.")
    pending = replace(article(2, "Bu metin doğrulanmadı."), verification="third_party")
    aspects = (rp.Aspect("A1", "Süre", "başvuru süresi"), rp.Aspect("A2", "Koşullar", "başvuru koşulları"))
    async def retrieve(query):
        if "koşul" in query:
            raise RuntimeError("secret must not be logged")
        return [ready, pending]
    result, rows = asyncio.run(rp.search_aspects(aspects, retrieve))
    assert rows == [ready] and result.failed == frozenset({"A2"})
    assert result.payload(rows)[1]["sources"] == []


def test_fanout_is_bounded_to_two_concurrent_readers():
    active = maximum = 0
    async def retrieve(query):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return []
    aspects = tuple(rp.Aspect(f"A{i}", "Konu", "arama") for i in range(5))
    asyncio.run(rp.search_aspects(aspects, retrieve))
    assert maximum == 2


def test_selection_reserves_sources_for_different_aspects():
    a, b = article(1, "Başvuru süresi tebliğden başlar."), article(2, "Başvuruda belge sunulur.")
    other_chunk = replace(a, chunk_id=UUID(int=3))
    selected = rp.select_contexts([a, other_chunk], [b], evidence(a, b), 2, "Başvuru hakkında bilgi")
    assert [c.chunk_id for c in selected] == [a.chunk_id, b.chunk_id]


def planned_draft(a, b):
    return {"claims": [{"text": c.content, "evidence": [{"source": i, "quote": c.content}]}
                       for i, c in enumerate([a, b], 1)], "question": None,
            "aspect_coverage": [{"aspect": f"A{i}", "status": "answered", "claims": [i]} for i in (1, 2)]}


def test_every_aspect_is_linked_to_checked_claims_and_reaches_independent_checker():
    a, b = article(1, "Başvuru süresi tebliğden başlar."), article(2, "Başvuruda belge sunulur.")
    checker = Provider(approved(2))
    result = synthesize_answer(Provider(planned_draft(a,b)), checker_provider=checker,
        question="Başvuru hakkında bilgi", contexts=[a,b], research_evidence=evidence(a,b))
    assert result and result.grounded
    payload = json.loads(checker.calls[0]["prompt"])
    assert len(payload["research_plan"]) == len(payload["aspect_coverage"]) == 2
    assert "yalnız aynı kaynak numarasını" in checker.calls[0]["system_instruction"]


@pytest.mark.parametrize("bad", [
    [{"aspect":"A1","status":"answered","claims":[1]}],
    [{"aspect":"A1","status":"answered","claims":[1]}, {"aspect":"A1","status":"answered","claims":[2]}],
    [{"aspect":"A1","status":"answered","claims":[1]}, {"aspect":"A2","status":"answered","claims":[99]}],
    [{"aspect":"A1","status":"answered","claims":[1]}, {"aspect":"A2","status":"needs_input","claims":[]}],
])
def test_missing_duplicate_invented_or_wrong_source_coverage_fails_closed(bad):
    a, b = article(1, "Başvuru süresi tebliğden başlar."), article(2, "Başvuruda belge sunulur.")
    value = planned_draft(a,b)
    value["aspect_coverage"] = bad
    checker = Provider(approved(2))
    result = synthesize_answer(Provider(value), checker_provider=checker, question="Başvuru hakkında bilgi",
        contexts=[a,b], research_evidence=evidence(a,b), repair_attempts=0)
    assert result is None and checker.calls == []


def test_declared_source_gap_is_rendered_not_silently_counted_as_complete():
    a, b = article(1, "Başvuru süresi tebliğden başlar."), article(2, "Başvuruda belge sunulur.")
    value = planned_draft(a,b)
    value["claims"].pop()
    value["aspect_coverage"][1] = {"aspect":"A2", "status":"source_gap", "claims":[]}
    diagnostic = {}
    result = synthesize_answer(Provider(value), checker_provider=Provider(approved()), question="Başvuru hakkında bilgi",
        contexts=[a,b], research_evidence=evidence(a,b), diagnostics=diagnostic)
    assert result and result.grounded and "doğrulayamıyorum" in result.text
    assert diagnostic["aspect_coverage"][1]["status"] == "source_gap"


def test_source_number_overlap_cannot_override_independent_relevance_rejection():
    a, b = article(1, "Başvuru süresi tebliğden başlar."), article(2, "Başvuruda belge sunulur.")
    checker = Provider(approved(2, coverage_preserved=False))
    result = synthesize_answer(Provider(planned_draft(a,b)), checker_provider=checker, question="Başvuru hakkında bilgi",
        contexts=[a,b], research_evidence=evidence(a,b), repair_attempts=0)
    assert result is None


def test_private_documents_reject_a_cloud_planning_artifact_before_any_generation():
    a = replace(article(1, "Kullanıcı belgesi."), source_type="document", verification="user_document")
    writer = Provider()
    assert synthesize_answer(writer, question="Belgeyi incele", contexts=[a], research_evidence=evidence(a)) is None
    assert writer.calls == []
