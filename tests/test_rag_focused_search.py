"""Full-corpus selective search without changing trust or answer validation."""
from dataclasses import replace
from uuid import UUID
import os

import psycopg
import pytest

from api.ai import retrieval
from api.ai.relevance import focused_intent_tsquery, intent_tsquery, question_intent
from tests.factories import court_decision_context

QUESTION = 'İcra takibinde itirazın iptali davası süresi nedir?'
TEXT = 'İtirazın iptali davası süresi somut olayda değerlendirilmiştir.'


def candidate(i, *, pending=True):
    return replace(court_decision_context(content=TEXT), source_id=UUID(int=i),
                   chunk_id=UUID(int=1000+i), verification='third_party' if pending else 'official')


def test_sql_uses_full_forms_not_double_stemmed_python_prefix():
    query = intent_tsquery(question_intent('Kira artışı nasıl yapılır?'))
    assert 'artırılması' in query and 'artırım' in query
    assert ' | artır)' not in query and ' | artır | ' not in query
    assert 'kira' in query and 'tüfe' in query


def test_focus_is_a_statute_hint_not_a_predetermined_answer():
    query = focused_intent_tsquery(QUESTION, question_intent(QUESTION))
    assert '2004' in query and '67' in query
    assert 'itirazın <-> iptal' in query
    assert 'bir' not in query and 'yıl' not in query
    question = 'İtirazın iptali davasında deliller nelerdir?'
    assert focused_intent_tsquery(question, question_intent(question)) is None
    question = 'Ortak velayet şartları nelerdir?'
    assert focused_intent_tsquery(question, question_intent(question)) is None


def test_rent_focus_uses_reference_without_adding_a_legal_conclusion():
    question = 'Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?'
    query = focused_intent_tsquery(question, question_intent(question))
    assert query == f'({intent_tsquery(question_intent(question))}) & 6098 & 344'
    assert 'yüzde' not in query and 'geçersiz' not in query


@pytest.mark.parametrize('question', [
    'Kıdem tazminatına hak kazanma şartları nelerdir?',
    'Kıdem tazminatının koşulları nelerdir?',
    'İşçi kıdem tazminatına nasıl hak kazanır?',
])
def test_severance_entitlement_uses_reference_not_an_expected_answer(question):
    query = focused_intent_tsquery(question, question_intent(question))
    assert query == f'({intent_tsquery(question_intent(question))}) & 1475 & 14'


@pytest.mark.parametrize('question', [
    'Kıdem tazminatı şartlarına ilişkin Yargıtay kararları nelerdir?',
    'Kıdem tazminatı şartları hakkında emsal arıyorum',
    'Kıdem tazminatı şartları nasıl ispat edilir?',
    'Kıdem tazminatına hak kazanmak için hangi deliller gerekir?',
    'Kıdem tazminatı hesabında ücret nedir?',
    'İtirazın iptali süresi hakkındaki içtihatları bul',
    'Kira artışı hakkında Yargıtay kararları nelerdir?',
    'Kira artışı talebi nasıl ispat edilir?',
    'Ortak velayet şartları nelerdir?',
])
def test_focus_does_not_narrow_case_law_evidence_or_unmeasured_topics(question):
    assert focused_intent_tsquery(question, question_intent(question)) is None


@pytest.mark.parametrize('question,text', [
    (QUESTION, TEXT),
    ('Kıdem tazminatına hak kazanma şartları nelerdir?',
     'Kıdem tazminatı işçinin fesih durumuna göre değerlendirilmiştir.'),
    ('Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?',
     'Kira artışı tüketici fiyat endeksine göre değerlendirilmiştir.'),
])
def test_sufficient_distinct_focused_candidates_keep_pending_searchable(monkeypatch, question, text):
    calls = []
    def execute(conn, sql, params, **kwargs):
        calls.append((sql, params, kwargs))
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return []
        return [replace(candidate(i), content=text) for i in range(1, 55)]
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    stats = {}
    rows = retrieval.retrieve_contexts(object(), question=question, top_k=48, diagnostics=stats)
    assert len(rows) == 48 and all(c.verification == 'third_party' for c in rows)
    assert len(calls) == 2 and calls[1][2]['timeout'] == '8s'
    assert 'legal_rag_current_lexical_hits(' in calls[1][0]
    assert '_bounded' not in calls[1][0]
    assert stats['lexical_strategy'] == 'statute_linked' and not stats['exhaustive']


def test_sparse_focused_search_falls_back_with_remaining_budget_and_deduplicates(monkeypatch):
    import time
    clock, calls = [0.0], []
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def execute(conn, sql, params, **kwargs):
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return []
        calls.append((params, kwargs))
        clock[0] += 1
        return [candidate(1)] if len(calls) == 1 else [candidate(1), candidate(2, pending=False)]
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    stats = {}
    rows = retrieval.retrieve_contexts(object(), question=QUESTION, top_k=48, diagnostics=stats)
    assert len(rows) == 2 and stats['lexical_candidates'] == 2
    assert calls[0][1]['timeout'] == '8s' and calls[1][1]['timeout'] == '7000ms'
    assert calls[1][0]['intent_query'] == intent_tsquery(question_intent(QUESTION))
    assert stats['lexical_strategy'] == 'statute_linked_then_broad'


def test_duplicate_chunks_do_not_count_as_distinct_focused_sources(monkeypatch):
    calls = []
    def execute(conn, sql, params, **kwargs):
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return []
        calls.append(params)
        return [replace(candidate(1), chunk_id=UUID(int=i)) for i in range(1, 50)]
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    retrieval.retrieve_contexts(object(), question=QUESTION, top_k=48)
    assert len(calls) == 2


def test_exhausted_deadline_does_not_launch_another_four_second_query(monkeypatch):
    import time
    import pytest
    clock, calls = [0.0], []
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])
    def execute(conn, sql, params, **kwargs):
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return []
        if '_tiered(' not in sql:
            calls.append(params)
        clock[0] += 4.1
        raise psycopg.errors.QueryCanceled()
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    stats = {}
    with pytest.raises(psycopg.errors.QueryCanceled):
        retrieval.retrieve_contexts(object(), question=QUESTION, top_k=48, diagnostics=stats)
    assert len(calls) == 1 and stats['partial']


def test_historical_search_keeps_date_and_does_not_use_current_only_function(monkeypatch):
    from datetime import date
    calls = []
    def execute(conn, sql, params, **kwargs):
        calls.append((sql, params))
        return []
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    retrieval.retrieve_contexts(object(), question=QUESTION, top_k=48, as_of=date(2020,1,1))
    for sql, params in calls:
        assert params['as_of'] == date(2020,1,1)
        assert 'legal_rag_current_lexical_hits(' not in sql


@pytest.mark.skipif(not os.getenv('NHR_TEST_DATABASE_URL'), reason='isolated test DB required')
@pytest.mark.parametrize('text', [
    'Kira bedelinin artırılması konusu değerlendirilmiştir.',
    'Kira artırım talebi değerlendirilmiştir.',
    'Kira artışı konusu değerlendirilmiştir.',
])
def test_turkish_dictionary_matches_real_increase_forms(text):
    query = intent_tsquery(question_intent('Kira artışı nasıl yapılır?'))
    with psycopg.connect(os.environ['NHR_TEST_DATABASE_URL']) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        matched, parsed = connection.execute(
            "SELECT to_tsvector('turkish', %s) @@ to_tsquery('turkish', %s), "
            "to_tsquery('turkish', %s)::text", (text, query, query)).fetchone()
        assert matched
        assert "'ar'" not in parsed
