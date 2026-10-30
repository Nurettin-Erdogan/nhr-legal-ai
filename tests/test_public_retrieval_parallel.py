"""Public lanes overlap without sharing a transaction or weakening source gates."""
from contextlib import contextmanager
from threading import Event

import psycopg
import pytest

from api.ai import retrieval, vector_index
from tests.factories import court_decision_context


def test_verbose_query_with_no_text_hits_searches_its_mandatory_concept(monkeypatch):
    context = court_decision_context(content='İşe iade talebinde otuz işçi koşulu incelenmiştir.')
    calls = []
    def execute(conn, sql, params, **kwargs):
        calls.append(dict(params))
        return [context] if params.get('question') == 'işe iade' else []
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    monkeypatch.setattr(retrieval, 'relevant_contexts', lambda q, rows: rows)
    result = retrieval.retrieve_contexts(object(), question='2026 yılı itibarıyla işe iade şartlarını iki Yargıtay kararıyla göster', top_k=4)
    assert context in result
    assert any(p.get('question') == 'işe iade' and p['required_phrase'] == 'işe iade' and p['as_of'] is None for p in calls)


def test_related_legislation_search_survives_a_successful_topic_hint(monkeypatch):
    from dataclasses import replace
    from tests.factories import legislation_context
    primary = legislation_context()
    related = replace(legislation_context(
        chunk_id="00000000-0000-0000-0000-000000000041",
        source_id="00000000-0000-0000-0000-000000000042"),
        law_no="6325", article_no="18/B", content="Kira uyuşmazlıklarında arabulucuya başvurulmuş olması dava şartıdır.")
    monkeypatch.setattr(retrieval, "question_intent", lambda q: type("Intent", (), {"statute": ("4857", "25")})())
    monkeypatch.setattr(retrieval, "intent_tsquery", lambda intent: "kira")
    monkeypatch.setattr(retrieval, "focused_intent_tsquery", lambda *args: None)
    monkeypatch.setattr(retrieval, "relevant_contexts", lambda q, contexts: contexts)
    monkeypatch.setattr(retrieval, "merge_lexical_hits", lambda q, statutes, candidates, k: statutes + candidates)
    visited = []

    def execute(conn, sql, params, *, timeout):
        visited.append(sql)
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return [primary]
        if sql == retrieval.LEGISLATION_M3_SQL:
            return [related]
        return []

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    result = retrieval.retrieve_contexts(object(), question="Kira uyuşmazlığında arabuluculuk", top_k=4,
        legislation_embedding=[0.0] * 1024, expand_legislation=True)
    assert retrieval.LEGISLATION_M3_SQL in visited
    assert primary in result and related in result


@pytest.mark.parametrize("parallel", [False, True])
def test_vector_connections_are_isolated_only_when_explicitly_enabled(monkeypatch, parallel):
    original, isolated = object(), object()
    vector_started, lexical_started = Event(), Event()
    context = court_decision_context(content="Kira artış uyuşmazlığı tüketici fiyat endeksi oranıyla ilgilidir.")

    @contextmanager
    def connection():
        yield isolated

    def execute(conn, sql, params, *, timeout):
        if sql == retrieval.SEMANTIC_RETRIEVAL_SQL:
            assert conn is (isolated if parallel else original)
            vector_started.set()
            if parallel:
                assert lexical_started.wait(2), "lexical search did not overlap"
        elif "legal_rag_current_lexical_hits(" in sql:
            assert conn is original
            assert vector_started.wait(2)
            lexical_started.set()
        return [context]

    monkeypatch.setattr("api.db.database_connection", connection)
    monkeypatch.setattr(vector_index, "shared_vector_index_ready", lambda conn: True)
    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    result = retrieval.retrieve_contexts(
        original, question="6098 kira artış uyuşmazlığı", top_k=4,
        query_embedding=[0.0] * 768, embedding_model="test",
        parallel_public_vectors=parallel,
    )
    assert result and any(c.chunk_id == context.chunk_id for c in result)


def test_optional_vector_connection_failure_keeps_lexical_results(monkeypatch):
    @contextmanager
    def broken():
        raise psycopg.OperationalError("unavailable")
        yield

    monkeypatch.setattr("api.db.database_connection", broken)
    monkeypatch.setattr(vector_index, "shared_vector_index_ready", lambda conn: True)
    context = court_decision_context(content="Kira artış uyuşmazlığı tüketici fiyat endeksi oranıyla ilgilidir.")
    monkeypatch.setattr(retrieval, "_execute_retrieval", lambda *a, **kw: [context])
    diagnostics = {}
    retrieval.retrieve_contexts(
        object(), question="6098 kira artış uyuşmazlığı", top_k=4,
        query_embedding=[0.0] * 768, embedding_model="test",
        parallel_public_vectors=True, diagnostics=diagnostics,
    )
    assert diagnostics["partial"] is True
    assert any(b["status"] == "connection_error" for b in diagnostics["branches"])


def test_semantic_queries_do_not_inherit_short_statement_deadlines(monkeypatch):
    visited = []
    monkeypatch.setattr(vector_index, 'shared_vector_index_ready', lambda conn: True)
    def execute(conn, sql, params, *, timeout):
        if sql in (retrieval.SEMANTIC_RETRIEVAL_SQL, retrieval.LEGISLATION_SEMANTIC_SQL, retrieval.LEGISLATION_M3_SQL):
            visited.append(timeout)
            assert timeout == '0'
        return []
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    retrieval.retrieve_contexts(object(), question='Kira uyuşmazlıklarında arabuluculuk', top_k=4,
        query_embedding=[0.0]*768, embedding_model='test', legislation_embedding=[0.0]*1024)
    assert len(visited) == 3
