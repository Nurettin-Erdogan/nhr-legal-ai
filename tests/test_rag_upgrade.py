"""Synthetic regressions: relevance, deadlines, provider switch and explanation."""
from dataclasses import replace
import json

import psycopg
import pytest

from api.ai import retrieval
from api.ai.evidence_selection import evidence_candidates
from api.ai.explanation import explain_verified_answer, validate_claims
from api.ai.providers import create_provider
from api.ai.relevance import passage_relevant
from api.ai.verification import verify_answer
from tests.factories import court_decision_context, legislation_context


RENT = 'Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?'
HARBOR = 'Aksaklıkların düzeltilmediği belirlenirse balıkçı barınağının kira sözleşmesi feshedilir.'


def test_verified_but_irrelevant_harbor_answer_is_rejected():
    context = court_decision_context(content=HARBOR)
    assert not evidence_candidates(RENT, [context])
    assert not verify_answer(HARBOR + ' [K1]', [context], question=RENT).grounded


@pytest.mark.parametrize('question,text', [
    ('Kıdem tazminatı şartları nelerdir?', 'Emekli ikramiyesi kıdem tazminatı tavanına tabidir.'),
    ('Yıllık izin alacağının ispat yükü kimde?', 'Yıllık izin alacağı ödenir.'),
    ('Deneme Kanunu itiraz harcı kaç lira?', 'İtiraz yedi gün içinde yapılır.'),
])
def test_topic_or_requested_fact_mismatch(question, text):
    assert not passage_relevant(question, text)


def test_qwen_is_local_without_removing_deepseek():
    for name, model in [('qwen','qwen3.5:4b'), ('deepseek','deepseek-r1:8b')]:
        provider = create_provider(provider_name=name, model=model)
        assert provider.name == name and provider.model == model


def test_explicit_statute_uses_direct_lookup_and_no_broad_scan(monkeypatch):
    calls = []
    def execute(connection, sql, params, **kw):
        calls.append((sql, params, kw))
        return []
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    assert retrieval.retrieve_contexts(object(), question='2577 sayılı Kanun madde 7 nedir?', top_k=6) == []
    assert len(calls) == 1 and calls[0][0] == retrieval.STATUTE_RETRIEVAL_SQL
    assert calls[0][2]['timeout'] == '3s'


def test_optional_search_timeout_keeps_verified_statute(monkeypatch):
    context = replace(legislation_context(content='Kira artışı tüketici fiyat endeksine bağlıdır.'),
                      law_no='6098', article_no='344')
    calls = []
    def execute(connection, sql, params, **kw):
        calls.append(sql)
        if sql == retrieval.STATUTE_RETRIEVAL_SQL:
            return [context]
        raise psycopg.errors.QueryCanceled()
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    diagnostics = {}
    result = retrieval.retrieve_contexts(object(), question=RENT, top_k=6, diagnostics=diagnostics,
                                         query_embedding=[0.1]*768, embedding_model='nomic-embed-text')
    assert result == [context]
    assert diagnostics['partial']
    assert len(calls) == 4  # statute + ANN + independent lexical branch + katmanlı yeniden deneme


def test_all_timeout_is_failure_not_empty_corpus(monkeypatch):
    def execute(*a, **kw):
        raise psycopg.errors.QueryCanceled()
    monkeypatch.setattr(retrieval, '_execute_retrieval', execute)
    with pytest.raises(psycopg.errors.QueryCanceled):
        retrieval.retrieve_contexts(object(), question=RENT, top_k=6)


def test_hybrid_has_separate_bounded_branch_and_model_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(retrieval, '_execute_retrieval',
        lambda c, sql, params, **kw: calls.append((sql, params, kw)) or [])
    retrieval.retrieve_contexts(object(), question='Sözleşme uyuşmazlığı', top_k=6,
                                query_embedding=[0.1]*768, embedding_model='nomic-embed-text')
    assert len(calls) == 2
    assert calls[0][0] == retrieval.SEMANTIC_RETRIEVAL_SQL
    assert calls[0][1]['embedding_model'] == 'nomic-embed-text'
    assert calls[0][2]['timeout'] == '3s'
    assert 'ORDER BY chunk.embedding <=>' in calls[0][0]
    assert 'row_number' not in calls[0][0]


class Replies:
    def __init__(self, *replies):
        self.replies = iter(replies)
    def generate(self, **kw):
        return json.dumps(next(self.replies))


def supported():
    c = court_decision_context(content='Deneme başvurusu yedi gün içinde yazılı yapılır.')
    return verify_answer(c.content + ' [K1]', [c])


@pytest.mark.parametrize('claim', [
    {'text':'Başvuru 30 gün içinde yapılır.', 'sources':[1]},
    {'text':'Başvuru yazılı yapılır.', 'sources':[99]},
    {'text':'Başvuru yazılı yapılır. [K1]', 'sources':[1]},
    {'text':'Başvuru yazılı yapılır.', 'sources':[True]},
])
def test_explanation_mechanical_checks(claim):
    assert validate_claims(json.dumps({'claims':[claim]}), supported(), 'Başvuru nasıl yapılır?') is None


@pytest.mark.parametrize('field', ['supported','relevant','scope_preserved','coverage_preserved'])
def test_explanation_rejects_any_failed_semantic_check(field):
    original = supported()
    verdict = dict(supported=True,relevant=True,scope_preserved=True,coverage_preserved=True)
    verdict[field] = False
    provider = Replies({'claims':[{'text':'Başvuru yazılı yapılır.', 'sources':[1]}]},verdict)
    assert explain_verified_answer(provider, question='Başvuru nasıl yapılır?', answer=original) == original


def test_explanation_returns_only_resolved_citations_after_checks():
    provider = Replies({'claims':[{'text':'Deneme başvurusu yedi gün içinde yazılı yapılır.', 'sources':[1]}]},
        dict(supported=True,relevant=True,scope_preserved=True,coverage_preserved=True))
    result = explain_verified_answer(provider,question='Başvuru nasıl yapılır?',answer=supported())
    assert result.grounded and '[K1]' in result.text and len(result.contexts)==1


def test_enumerated_conditions_are_not_summarized_with_missing_branches():
    c = court_decision_context(content='Deneme koşulları: 1. A belgesi, 2. B belgesi, 3. C belgesi birlikte sunulur.')
    answer = verify_answer(c.content + ' [K1]', [c])
    assert answer.grounded
    # No model call: observed local-judge blind spot must fail closed in code.
    assert explain_verified_answer(Replies(), question='Deneme koşulları nedir?', answer=answer) == answer


def test_statutory_exception_is_preserved_without_asking_model_to_remember_it():
    from api.ai.evidence_selection import preserve_statutory_scope
    c = legislation_context(content='Kira artışı endekse bağlıdır. Ancak kira artışı için bu sentetik istisna ayrıca uygulanır.')
    result = preserve_statutory_scope('Kira artışı endekse bağlıdır. [K1]', [c], RENT)
    assert 'istisna' in result
    assert verify_answer(result, [c], question=RENT).grounded


def test_word_inside_another_word_is_not_an_annual_leave_match():
    assert not passage_relevant('Yıllık izin alacağının ispat yükü kimde?', 'Sizin ispat yükünüz bulunmaktadır.')


def test_case_findings_cannot_be_generalized_by_the_summary_model():
    c = court_decision_context(content='Somut olayda ortak velayetin çocuğun yararına olmadığı açıklanmıştır.')
    answer = verify_answer(c.content+' [K1]',[c])
    assert explain_verified_answer(Replies(),question='Ortak velayet şartları?',answer=answer)==answer


def test_partial_answer_does_not_pretend_to_cover_the_requested_deadline():
    from api.ai.explanation import with_coverage_notice
    c = court_decision_context(content='Bireysel başvuru yollarının tüketilmesi gerekir.')
    answer = verify_answer(c.content+' [K1]',[c])
    result = with_coverage_notice(answer,'Bireysel başvuru süresi ve şartları nelerdir?')
    assert 'süreyi bu alıntılarla doğrulayamadım' in result.text
    assert result.contexts==answer.contexts


def test_retrieval_keeps_relevant_fragments_but_generation_does_not_quote_them():
    from api.ai.relevance import context_relevant
    context = court_decision_context(content='PYTESTTARIH eski metin')
    assert context_relevant('PYTESTTARIH', context)
    assert evidence_candidates('PYTESTTARIH', [context]) == []
