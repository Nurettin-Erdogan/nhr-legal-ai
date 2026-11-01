from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api.ai import official_research as research
from tests.factories import legislation_context


def test_only_fixed_terms_leave_machine():
    text = 'Ahmet Yılmaz TC 12345678901 250.000 TL borcumu ödemedi adresi test@example.com'
    assert research.safe_topics(text) == ('itirazın iptali',)
    assert research.safe_topics('pizza tarifi') == ()
    assert research.statute_references(['6098 sayılı Kanun madde 315'], []) == (('6098', '315'),)
    assert research.statute_references(['https://evil.test/ örnek'], []) == ()


@pytest.mark.parametrize('scope,contexts', [
    (False, []), (True, [replace(legislation_context(), source_type='document')]),
])
def test_private_scope_never_calls_adapters(monkeypatch, scope, contexts):
    monkeypatch.delenv('NHR_OFFLINE_AUDIT', raising=False)
    def forbidden(*args):
        raise AssertionError('private information must not leave machine')
    result = research.research_official(['6098 sayılı Kanun madde 315'], contexts,
        public_scope=scope, fetch_law=forbidden, court_search=forbidden)
    assert not result.contexts
    assert result.statuses[0]['status'] == 'private_scope_blocked'


def test_offline_mode_never_calls_adapters(monkeypatch):
    monkeypatch.setenv('NHR_OFFLINE_AUDIT', '1')
    result = research.research_official(['6098 sayılı Kanun madde 315'], [], public_scope=True,
        fetch_law=lambda *_: pytest.fail('network call'))
    assert result.statuses[0]['status'] == 'offline'


def test_fetch_full_verify_store_then_load_in_that_order(monkeypatch):
    monkeypatch.delenv('NHR_OFFLINE_AUDIT', raising=False)
    calls, source_id = [], uuid4()
    context = legislation_context()
    def fetch(law):
        calls.append(('fetch', law))
        return 'official identity', 'full official document'
    def store(document, full, article):
        assert full == 'full official document'
        calls.append(('store', article))
        return source_id
    def load(ids):
        assert ids == (source_id,)
        calls.append(('load',))
        return [context]
    result = research.research_official(['6098 sayılı Kanun madde 315'], [], public_scope=True,
        fetch_law=fetch, store_article=store, load_contexts=load)
    assert calls == [('fetch', '6098'), ('store', '315'), ('load',)]
    assert result.contexts == (context,)
    assert result.statuses == ({'source': 'mevzuat', 'status': 'document_verified'},)


def test_one_document_download_for_multiple_articles(monkeypatch):
    monkeypatch.delenv('NHR_OFFLINE_AUDIT', raising=False)
    calls = []
    result = research.research_official(['6098 sayılı Kanun madde 315', '6098 sayılı Kanun madde 344'], [],
        public_scope=True, fetch_law=lambda law: (calls.append(law) or ('doc', 'full')),
        store_article=lambda *args: uuid4(), load_contexts=lambda ids: [])
    assert calls == ['6098']
    assert len(result.statuses) == 2


def test_blocked_portal_does_not_retry_another_keyword(monkeypatch):
    monkeypatch.delenv('NHR_OFFLINE_AUDIT', raising=False)
    calls = []
    def blocked(topic):
        calls.append(topic)
        raise RuntimeError('secret error detail must not appear in diagnostics')
    result = research.research_official(['kıdem ve ihbar tazminatı'], [], public_scope=True, court_search=blocked)
    assert len(calls) == 1
    assert result.statuses == ({'source': 'yargitay', 'status': 'unavailable_or_unverified',
                                'exhaustive': False, 'failure_type': 'RuntimeError'},)
    assert 'secret' not in str(result)


def test_search_hit_is_never_evidence_without_persisted_document(monkeypatch):
    monkeypatch.delenv('NHR_OFFLINE_AUDIT', raising=False)
    result = research.research_official(['kira'], [], public_scope=True,
        court_search=lambda topic: ([], 1000000), load_contexts=lambda ids: pytest.fail('no persisted IDs'))
    assert result.contexts == ()
    assert result.statuses[0]['matched'] == 1000000
    assert result.statuses[0]['documents'] == 0
    assert result.statuses[0]['exhaustive'] is False


@pytest.mark.parametrize('url,kind,title,body', [
    ('https://evil.test/MevzuatMetin/1.5.6098.pdf', 1, 'Türk Borçlar Kanunu', 'Türk Borçlar Kanunu Kanun Numarası : 6098'),
    ('https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf', 1, 'Türk Borçlar Kanunu', 'Türk Borçlar Kanunu Kanun Numarası : 6098'),
    ('https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf', 2, 'Türk Borçlar Kanunu', 'Türk Borçlar Kanunu Kanun Numarası : 6098'),
    ('https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf', 1, 'İş Kanunu', 'Türk Borçlar Kanunu Kanun Numarası : 6098'),
    ('https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf', 1, 'Türk Borçlar Kanunu', 'Türk Borçlar Kanunu Kanun Numarası : 4857'),
])
def test_identity_mismatch_refused(url, kind, title, body):
    with pytest.raises(ValueError):
        research.validate_law_document(SimpleNamespace(pdf_url=url, legislation_type=kind,
            law_no='6098', law_name=title), body)


def test_correct_identity_accepted():
    research.validate_law_document(SimpleNamespace(pdf_url='https://www.mevzuat.gov.tr/MevzuatMetin/1.5.6098.pdf',
        legislation_type=1, law_no='6098', law_name='Türk Borçlar Kanunu'),
        'TÜRK BORÇLAR KANUNU\nKanun Numarası : 6098')


def test_public_cache_single_flight_and_failure_cooldown():
    cache, calls = {}, []
    def fetch(key):
        calls.append(key)
        return ('official text',)
    assert research._cached(cache, '6098', fetch, ttl=300) == ('official text',)
    assert research._cached(cache, '6098', fetch, ttl=300) == ('official text',)
    assert calls == ['6098']
    def failed(key):
        calls.append(key)
        raise RuntimeError('do not retain transport details')
    with pytest.raises(RuntimeError):
        research._cached(cache, 'failed', failed, ttl=300)
    with pytest.raises(ValueError):
        research._cached(cache, 'failed', failed, ttl=300)
    assert calls == ['6098', 'failed']
    assert 'transport details' not in str(cache)


def test_other_official_host_is_not_a_law_document():
    with pytest.raises(ValueError):
        research.validate_law_document(SimpleNamespace(
            pdf_url='https://www.tbmm.gov.tr/MevzuatMetin/1.5.6098.pdf',
            legislation_type=1, law_no='6098', law_name='Türk Borçlar Kanunu'),
            'TÜRK BORÇLAR KANUNU\nKanun Numarası : 6098')


@pytest.mark.parametrize('scope', [True, False])
def test_pipeline_merges_web_evidence_before_writer(monkeypatch, scope):
    from contextlib import contextmanager
    from api.ai import pipeline, free_answer, provision_context
    from api.ai.verification import VerifiedAnswer
    local = legislation_context(content='Madde 315 - Kiracı borcunu ödemelidir.')
    web = replace(legislation_context(content='Madde 344 - Artış taraflarca belirlenir.'),
                  chunk_id=uuid4(), source_id=uuid4(), article_no='344')
    @contextmanager
    def connection():
        yield object()
    monkeypatch.setattr(pipeline, 'database_connection', connection)
    monkeypatch.setattr(pipeline, 'get_settings', lambda: SimpleNamespace(
        legislation_embedding_model='', cloud_ai_provider='', official_web_research_enabled=True))
    monkeypatch.setattr(pipeline, 'retrieve_contexts', lambda *a, **kw: [local])
    monkeypatch.setattr(pipeline, '_case_statute_contexts', lambda *a, **kw: [local])
    monkeypatch.setattr(free_answer, 'plan_question', lambda *a: [('Kira artışı', ('kira artışı',))])
    monkeypatch.setattr(provision_context, 'restore_provisions', lambda contexts, db: contexts)
    monkeypatch.setattr('api.ai.decision_context.restore_decisions', lambda contexts, db: contexts)
    calls = []
    def search(queries, contexts, *, public_scope):
        assert public_scope is True
        assert calls == ['restore'], 'local canonical recovery must precede outbound research'
        calls.append('web')
        return research.ResearchResult((web,), ({'source': 'mevzuat', 'status': 'document_verified'},))
    monkeypatch.setattr(research, 'research_official', search)
    def restore(contexts, db):
        if not calls:
            calls.append('restore')
        return contexts
    monkeypatch.setattr(provision_context, 'restore_provisions', restore)
    def write(provider, **kwargs):
        calls.append('writer')
        assert (web in kwargs['contexts']) is scope
        return VerifiedAnswer('Kaynaklı cevap.', tuple(kwargs['contexts']), ())
    monkeypatch.setattr(free_answer, 'free_verified_answer', write)
    timings = pipeline.PipelineTimings()
    answer = pipeline._free_answer(object(), 'Kira artışı', [local], [], timings, object(), public_web_scope=scope)
    assert answer is not None
    assert calls == (['restore', 'web', 'writer'] if scope else ['restore', 'writer'])
