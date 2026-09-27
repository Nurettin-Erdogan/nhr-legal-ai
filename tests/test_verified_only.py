"""Verified-only publication: no portal failure may release pending evidence."""
from contextlib import contextmanager
from dataclasses import replace, asdict
from types import SimpleNamespace
import asyncio

import pytest
import psycopg
from fastapi import HTTPException

from api.ai import live_verify, pipeline, research
from api.ai.cache import answer_cache
from api.ai.trust import verified_contexts
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context, document_context


def pending():
    return replace(court_decision_context(), verification='third_party')


@pytest.fixture
def portal(monkeypatch):
    context = pending()
    rows = [{'id':context.source_id,'external_id':'yargitay:123','raw_text':context.content}]
    class Connection:
        def execute(self,*args):
            return SimpleNamespace(fetchall=lambda: rows)
    @contextmanager
    def connection():
        yield Connection()
    monkeypatch.setattr(live_verify,'database_connection',connection)
    return context, rows


@pytest.mark.parametrize('text', ['', 'Başka bir karar metnidir.'])
def test_empty_or_mismatching_portal_text_is_not_published(portal,text):
    context,_ = portal
    result=live_verify.verify_third_party_contexts([context],fetcher=lambda *a:text,
             promoter=lambda *a: pytest.fail('Mismatched source promoted'))
    assert result == []


def test_stale_chunk_is_not_blessed_by_matching_document(portal):
    context,_ = portal
    stale=replace(context,content='Bu değişmiş parça resmî metinde yer almıyor.')
    assert live_verify.verify_third_party_contexts([stale],fetcher=lambda *a:context.content,
             promoter=lambda *a:pytest.fail('Stale chunk promoted')) == []


def test_success_uses_official_url_and_only_after_promotion(portal):
    context,_ = portal
    calls=[]
    result=live_verify.verify_third_party_contexts([context],fetcher=lambda *a:context.content,
             promoter=lambda *a:calls.append(a))
    assert len(calls)==1 and len(result)==1
    assert result[0].verification=='official'
    assert 'karararama.yargitay.gov.tr' in result[0].source_url


def test_failed_promotion_is_not_published(portal):
    context,_=portal
    def fail(*args):
        raise psycopg.Error('write failed')
    assert live_verify.verify_third_party_contexts([context],fetcher=lambda *a:context.content,promoter=fail)==[]


def test_user_document_is_not_mislabelled_as_official_or_dropped():
    doc=replace(document_context(),verification='user_document')
    assert verified_contexts([pending(),doc])==[doc]
    assert verified_contexts([replace(pending(),verification='unknown')])==[]


def test_research_verifies_before_publishing_and_does_not_expose_candidate_total_as_verified(monkeypatch):
    context=pending()
    row=asdict(context)|{'total':50}
    class Connection:
        @contextmanager
        def transaction(self): yield
        def execute(self, sql, params=None):
            return SimpleNamespace(fetchall=lambda: [row] if params else [])
    @contextmanager
    def connection(): yield Connection()
    monkeypatch.setattr(research,'database_connection',connection)
    monkeypatch.setattr(research,'verify_third_party_contexts',lambda rows:rows)
    result=research.research_sources(q='kıdem tazminatı',limit=10,offset=0)
    assert result['results']==[] and result['total'] is None
    assert result['verification_pending']==1
    monkeypatch.setattr(research,'verify_third_party_contexts',lambda rows:[replace(c,verification='official') for c in rows])
    result=research.research_sources(q='kıdem tazminatı',limit=10,offset=0)
    assert result['results'][0]['verification']=='official'


@pytest.fixture
def answer_pipeline(monkeypatch):
    answer_cache.clear()
    settings=SimpleNamespace(ai_provider='deepseek',ai_model='test',ollama_base_url='http://127.0.0.1:11434',
        ollama_timeout_seconds=1,ollama_max_output_tokens=128,ollama_num_ctx=4096,
        ollama_keep_alive='30m',rag_query_embedding=False,rag_top_k=6,embedding_model='test',rag_context_chars=900)
    monkeypatch.setattr(pipeline,'get_settings',lambda:settings)
    monkeypatch.setattr(pipeline,'create_provider',lambda **k:SimpleNamespace(name='deepseek',model='test'))
    for name in ('pause_embeddings','resume_embeddings','unload_ollama_model'):
        if hasattr(pipeline,name): monkeypatch.setattr(pipeline,name,lambda *a,**k:None)
    monkeypatch.setattr(pipeline.verification_queue,'enqueue_in_background',lambda *a:None)
    monkeypatch.setattr(pipeline,'_retrieve',lambda *a,**k:[pending()])
    monkeypatch.setattr(pipeline,'generate_grounded_answer',lambda *a,**k:pytest.fail('Pending text reached model'))
    return monkeypatch


def test_no_model_cache_preview_or_answer_when_portal_did_not_verify(answer_pipeline):
    answer_pipeline.setattr(pipeline,'verify_third_party_contexts',lambda contexts, **kwargs:contexts)
    events=[]
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.execute_answer(AIAnswerRequest(question='Kıdem tazminatı şartları nelerdir?'),None,on_stage=events.append))
    assert error.value.status_code==422
    assert not any(e['stage'] in ('sources_found','generating','done') for e in events)
    assert len(answer_cache)==0


def test_verified_source_reaches_model_and_response(answer_pipeline):
    checked=[]
    def verify(contexts, **kwargs):
        checked.append(True)
        return [replace(c,verification='official') for c in contexts]
    def generate(*args,**kwargs):
        assert checked and all(c.verification=='official' for c in kwargs['contexts'])
        return kwargs['contexts'][0].content+' [K1]'
    answer_pipeline.setattr(pipeline,'verify_third_party_contexts',verify)
    answer_pipeline.setattr(pipeline,'generate_grounded_answer',generate)
    result,_=asyncio.run(pipeline.execute_answer(AIAnswerRequest(question='Kıdem tazminatı şartları nelerdir?'),None))
    assert result.grounded and all(c.verification=='official' for c in result.citations)
