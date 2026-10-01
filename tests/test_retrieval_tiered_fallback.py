"""RAG sözcük araması soğuk diskte zaman aşımına uğrarsa katmanlı sürüme düşer (ağ/DB gerektirmez)."""

from __future__ import annotations

import psycopg
import pytest

from api.ai import retrieval
from tests.factories import court_decision_context

QUESTION = "Kıdem tazminatı şartları nelerdir?"


def test_tiered_variant_rewrites_only_the_full_ranking_call():
    sql = retrieval.LEXICAL_RETRIEVAL_SQL
    tiered = retrieval._tiered_variant(sql)
    assert "legal_rag_current_lexical_hits_tiered(" in tiered
    assert "legal_rag_current_lexical_hits(" not in tiered
    assert f", {retrieval._TIERED_SEED_CAP})" in tiered.replace("\n", "")
    # Uygunluk süzgeci ve zaman koşulu dış sorguda aynen kalır.
    assert retrieval._VERIFIED_SOURCE_FILTER in tiered
    # Zaten katmanlı/ilgisiz SQL değişmez.
    assert retrieval._tiered_variant(retrieval.STATUTE_RETRIEVAL_SQL) == retrieval.STATUTE_RETRIEVAL_SQL
    assert retrieval._tiered_variant(retrieval.SEMANTIC_RETRIEVAL_SQL) == retrieval.SEMANTIC_RETRIEVAL_SQL


def _patched(monkeypatch, behaviour):
    calls: list[tuple[str, str]] = []

    def execute(connection, sql, params, *, timeout="15s"):
        calls.append(("tiered" if "_tiered(" in sql else "full", timeout))
        return behaviour(sql)

    monkeypatch.setattr(retrieval, "_execute_retrieval", execute)
    return calls


def test_timeout_falls_back_to_the_tiered_search_and_is_marked_partial(monkeypatch):
    context = court_decision_context()

    def behaviour(sql):
        if "_tiered(" not in sql:
            raise psycopg.errors.QueryCanceled("statement timeout")
        return [context]

    calls = _patched(monkeypatch, behaviour)
    diagnostics: dict = {}

    result = retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    assert [kind for kind, _ in calls if kind == "tiered"], calls
    assert result and diagnostics["partial"] is True
    statuses = [branch["status"] for branch in diagnostics["branches"]]
    assert "timeout_then_tiered" in statuses


def test_both_attempts_timing_out_still_raises_instead_of_pretending_the_corpus_is_empty(monkeypatch):
    def behaviour(sql):
        raise psycopg.errors.QueryCanceled("statement timeout")

    _patched(monkeypatch, behaviour)

    with pytest.raises(psycopg.errors.QueryCanceled):
        retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics={})


def test_a_fast_full_search_is_not_replaced_by_the_sampled_one(monkeypatch):
    context = court_decision_context()
    calls = _patched(monkeypatch, lambda sql: [context])
    diagnostics: dict = {}

    retrieval.retrieve_contexts(None, question=QUESTION, top_k=5, diagnostics=diagnostics)

    assert all(kind == "full" for kind, _ in calls)
    assert diagnostics["partial"] is False
