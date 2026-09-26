from contextlib import contextmanager
from dataclasses import asdict
from uuid import UUID

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.ai import research
from api.ai.search_plan import plan_search
from api.ai.passages import select_passage
from api.ai.rag import build_grounded_prompt
from api.ai.verification import verify_answer
from tests.factories import court_decision_context


def test_joint_custody_keeps_third_word_and_requires_compound():
    plan = plan_search("Boşanmada ortak velayet hangi şartlarda verilir?")
    assert plan.text == "boşanmada ortak velayet"
    assert plan.phrase == "ortak velayet"
    assert plan_search("Boşanmada ortak velâyetin şartları nedir?").phrase == "ortak velayet"
    assert plan_search("ortak çocuk için velayet").phrase == ""


def test_more_than_two_informative_terms_and_law_numbers_survive():
    plan = plan_search("4857 sayılı Kanun madde 25 haklı fesih nasıl yapılır?")
    assert "4857" in plan.text and "25" in plan.text
    assert "haklı fesih" in plan.text
    assert "nasıl" not in plan.text and "yapılır" not in plan.text


def test_research_has_no_top_k_or_arbitrary_candidate_cap():
    assert "NULL::integer" in research.RESEARCH_SQL
    assert "DISTINCT ON (ls.id)" in research.RESEARCH_SQL
    assert "count(*) OVER ()" in research.RESEARCH_SQL
    assert "candidate_limit" not in research.RESEARCH_SQL
    assert "bounded" not in research.RESEARCH_SQL
    assert "ls.deleted_at IS NULL" in research.RESEARCH_SQL
    assert "ls.is_current" in research.RESEARCH_SQL
    assert "bulk_seed" in research.RESEARCH_SQL


@pytest.fixture
def pages(monkeypatch):
    rows = []
    for number in range(25):
        context = court_decision_context(source_id=str(UUID(int=number + 100)))
        row = asdict(context)
        row["total"] = 25
        row["verification"] = "third_party" if number % 2 else "official"
        rows.append(row)
    statements = []

    class Connection:
        def execute(self, sql, params=None):
            statements.append((sql, params))
            selected = rows[params["offset"]:params["offset"] + params["limit"]] if params else []
            return type("Result", (), {"fetchall": lambda self: selected})()

    @contextmanager
    def connection():
        yield Connection()

    monkeypatch.setattr(research, "database_connection", connection)
    app = FastAPI()
    app.include_router(research.router, prefix="/api/ai")
    return TestClient(app), statements


def test_every_matching_source_is_reachable_without_two_source_limit(pages):
    client, statements = pages
    ids = []
    offset = 0
    while True:
        response = client.get("/api/ai/sources", params={"q": "ortak velayet", "offset": offset})
        assert response.status_code == 200
        page = response.json()
        assert page["total"] == 25
        assert page["results"][1]["verification"] == "third_party"
        ids.extend(source["source_id"] for source in page["results"])
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        offset = page["next_offset"]
    assert len(ids) == len(set(ids)) == 25
    assert sum(sql == "SET TRANSACTION READ ONLY" for sql, _ in statements) == 3


def test_http_bounds_and_empty_question(pages):
    client, _ = pages
    for params in ({"limit": 51}, {"offset": -1}, {"q": "hangi nasıl"}):
        assert client.get("/api/ai/sources", params={"q": "ortak velayet", **params}).status_code == 422


def test_timeout_never_returns_fake_empty_or_complete_results(monkeypatch):
    @contextmanager
    def connection():
        raise psycopg.errors.QueryCanceled("private connection details")
        yield

    monkeypatch.setattr(research, "database_connection", connection)
    with pytest.raises(research.HTTPException) as error:
        research.research_sources(q="ortak velayet", limit=10, offset=0)
    assert error.value.status_code == 504
    assert "private" not in error.value.detail


def test_late_relevant_complete_sentence_replaces_opening_clip():
    relevant = "Ortak velayet konusunda bu olayın koşulları değerlendirilmelidir."
    source = court_decision_context(content=("Bu paragraf başka konuyu anlatmaktadır. " * 30) + relevant)
    passage = select_passage(source.content, "Ortak velayet şartları nedir?", 150)
    assert relevant in passage
    assert len(passage) <= 150
    assert verify_answer(f"{passage} [K1]", [source]).grounded
    prompt = build_grounded_prompt("Ortak velayet şartları nedir?", [source], max_context_chars=150)
    assert relevant in prompt


def test_no_heading_or_cut_sentence_is_presented_as_evidence():
    assert select_passage("III. " + "ortak velayet " * 200 + ".", "ortak velayet", 100) == ""


def test_hybrid_model_context_does_not_expand_to_whole_candidate_pool(monkeypatch):
    from api.ai import retrieval

    rows = [court_decision_context(
        source_id=str(UUID(int=i + 100)), chunk_id=str(UUID(int=i + 200)),
    ) for i in range(24)]
    monkeypatch.setattr(retrieval, "_execute_retrieval", lambda *a: rows)
    monkeypatch.setattr(retrieval, "vector_literal", lambda vector: "[0]")
    selected = retrieval.retrieve_contexts(object(), question="Kıdem tazminatı", top_k=6, query_embedding=[0.1], embedding_model="test")
    assert len(selected) == 6


def test_phrase_is_not_silently_relaxed_to_unrelated_or_results(monkeypatch):
    from api.ai import retrieval

    calls = []
    def execute(connection, sql, params):
        calls.append(params)
        return []
    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    assert retrieval.retrieve_contexts(object(), question="Ortak velayet şartları?", top_k=6) == []
    assert len(calls) == 1
    assert calls[0]["required_phrase"] == "ortak velayet"
    assert calls[0]["candidate_limit"] >= 24
