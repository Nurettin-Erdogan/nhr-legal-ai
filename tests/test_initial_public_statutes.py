"""Initial exact seeds save discovery work, never claim complete coverage."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest

from api.ai import pipeline, provision_context
from api.schemas import AIAnswerRequest
from tests.factories import legislation_context

QUESTION = 'İşe iade davasının şartları nelerdir? Otuz işçi şartı nasıl hesaplanır ve hangi sürede başvurmalıyım?'


def setup_seed(monkeypatch):
    source = replace(legislation_context(content=(
        'İşveren, işçinin belirsiz süreli iş sözleşmesini feshederken geçerli bir sebebe dayanmak zorundadır.')),
        article_no='18')
    monkeypatch.setattr(pipeline, 'database_connection', lambda: nullcontext(object()))
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda rows, conn: rows)
    monkeypatch.setattr(pipeline, '_planned_statutes', lambda request, question: [source])
    return source


def test_complete_current_public_seed_is_provisional_and_keeps_original_question(monkeypatch):
    source = setup_seed(monkeypatch)
    request = AIAnswerRequest(question=QUESTION)
    diagnostics = {}
    assert pipeline._initial_public_statutes(request, QUESTION, diagnostics) == [source]
    assert request.question == QUESTION
    assert diagnostics['strategy'] == 'provisional_local_statutes'
    assert diagnostics['research_deferred'] is True and diagnostics['exhaustive'] is False
    assert 'provisional_seed_ms' in diagnostics


@pytest.mark.parametrize('scope', [
    {'as_of': date(2020, 1, 1)}, {'project_id': uuid4()}, {'case_id': uuid4()},
    {'office_project_id': uuid4()}, {'selected_document_ids': [uuid4()]},
])
def test_private_or_historical_scope_does_not_use_public_seed(monkeypatch, scope):
    def forbidden(*args):
        raise AssertionError('out-of-scope lookup')
    monkeypatch.setattr(pipeline, '_planned_statutes', forbidden)
    assert pipeline._initial_public_statutes(AIAnswerRequest(question=QUESTION, **scope), QUESTION, {}) == []


@pytest.mark.parametrize('question', [
    QUESTION + ' İki Yargıtay kararıyla açıkla.',
    '2018 yılında işten çıkarıldım, işe iade süresi ve şartları nedir?',
    'Bilinmeyen çok farklı bir konu ve başka bir konu?',
    'Kira artışı nasıl belirlenir?',
])
def test_case_law_dates_unknown_and_simple_requests_keep_their_original_paths(monkeypatch, question):
    monkeypatch.setattr(pipeline, '_planned_statutes', lambda *args: pytest.fail('unexpected seed lookup'))
    assert pipeline._initial_public_statutes(AIAnswerRequest(question=question), question, {}) == []


def test_unverified_unusable_and_mismatched_sources_cannot_become_seeds(monkeypatch):
    source = setup_seed(monkeypatch)
    request = AIAnswerRequest(question=QUESTION)
    for invalid in (
        replace(source, verification='third_party'),
        replace(source, content='Tamamlanmamış bir koşul ancak'),
        replace(source, content='Dernek yönetim kurulunu genel kurul seçer.'),
    ):
        monkeypatch.setattr(pipeline, '_planned_statutes', lambda *args: [invalid])
        assert pipeline._initial_public_statutes(request, QUESTION, {}) == []


def test_lookup_failure_falls_back_without_pretending_there_are_sources(monkeypatch):
    import psycopg
    def broken(*args):
        raise psycopg.OperationalError('fixture')
    monkeypatch.setattr(pipeline, '_planned_statutes', broken)
    info = {}
    assert pipeline._initial_public_statutes(AIAnswerRequest(question=QUESTION), QUESTION, info) == []
    assert info.get('strategy') is None
