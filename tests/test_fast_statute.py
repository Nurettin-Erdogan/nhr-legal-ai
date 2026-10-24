import asyncio
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from api.ai.fast_statute import fast_reference, try_fast_statute
from tests.factories import legislation_context

QUESTION = 'Kira sözleşmesinde TÜFE üzerinde artış istenirse ne yapılır?'
TEXT = 'Kira artışı bu sentetik örnekte tüketici fiyat endeksine bağlıdır.'


def statute(**kwargs):
    return replace(legislation_context(content=TEXT), law_no='6098', article_no='344', **kwargs)


@pytest.mark.parametrize('question', [
    'Kira artışı hakkında Yargıtay kararları nelerdir?',
    'Kıdem tazminatı şartları nasıl ispat edilir?',
    'Kira artışı 2017 yılında nasıldı?',
    'Kira artışı ve tahliye nasıl yapılır?',
    'Ortak velayet şartları nelerdir?',
    'Kıdem tazminatı nasıl hesaplanır?',
    'Kira artışı nedeniyle tahliye davası açılır mı?',
    'İtirazın iptali davası süresinde görevli mahkeme hangisi?',
    '6098 sayılı kanun madde 345 kira artışı hakkında ne der?',
    '657 sayılı kanunda kira artışı hangi koşullara bağlı?',
])
def test_ambiguous_case_law_and_historical_questions_keep_full_search(question):
    assert fast_reference(question) is None


def test_nonpayment_lookup_does_not_mix_general_and_product_leases():
    from api.ai.relevance import question_intent
    from api.ai.authority import answer_uses_primary_basis
    question = 'Kiracı kirayı ödemezse ev sahibi ne yapabilir?'
    assert fast_reference(question) == ('6098', '315')
    for special in ('Ürün kirası ödenmezse ne olur?', 'Tarla kirası ödenmezse ne olur?',
                    'Kira ödenmezse icra takibi nasıl yapılır?'):
        assert question_intent(special) is None
        assert fast_reference(special) is None
    general = replace(legislation_context(), law_no='6098', article_no='315')
    product = replace(general, chunk_id=uuid4(), article_no='362')
    assert answer_uses_primary_basis(question, [general], [general, product])
    assert not answer_uses_primary_basis(question, [product], [general, product])
    assert not answer_uses_primary_basis(question, [general, product], [general, product])


@pytest.mark.parametrize('options', [
    {'as_of': date(2020,1,1)}, {'project_id': uuid4()}, {'conversation_id': uuid4()},
])
def test_no_fast_path_for_historical_or_private_context(options):
    def forbidden(*args):
        raise AssertionError('No fast DB lookup')
    assert try_fast_statute(question=QUESTION, loader=forbidden, **options) == []


def test_complete_official_article_with_conditions_and_scope():
    info = {}
    def load(reference, limit):
        assert reference == ('6098','344') and limit == 7
        return [statute()]
    rows = try_fast_statute(question=QUESTION, loader=load, diagnostics=info)
    assert rows and info['research_deferred'] and info['strategy']=='verified_statute'
    assert info['exhaustive'] is False and info['partial'] is False


@pytest.mark.parametrize('rows', [
    [], [statute(verification='third_party')], [statute(effective_to=date(2018,1,1))],
    [statute(effective_from=date(2100,1,1))],
    [replace(statute(), article_no='345')],
    [statute(), statute(source_id=uuid4())],
    [statute()] * 7,
    [replace(statute(), content='İlgisiz balıkçı barınağı metnidir.')],
    [replace(statute(), content=TEXT + ' '.join(f'Ancak sentetik koşul {i} ayrıca saklıdır.' for i in range(300)))],
])
def test_pending_wrong_version_clipped_ambiguous_or_irrelevant_evidence_falls_back(rows):
    assert try_fast_statute(question=QUESTION, loader=lambda *a: rows) == []


def test_timeout_is_optional_failure_not_an_empty_corpus_claim():
    info = {}
    def timeout(*args):
        raise psycopg.errors.QueryCanceled()
    assert try_fast_statute(question=QUESTION, loader=timeout, diagnostics=info) == []
    assert info['fast_statute_status']=='unavailable' and 'research_deferred' not in info


@pytest.mark.parametrize('reject_fast_draft', [False, True])
def test_pipeline_skips_expensive_branches_but_retries_if_model_abstains(monkeypatch, reject_fast_draft):
    from api.ai import pipeline
    from api.ai.cache import answer_cache
    from api.schemas import AIAnswerRequest
    answer_cache.clear()
    settings = SimpleNamespace(ai_provider='qwen', ai_model='synthetic',
        ollama_base_url='http://127.0.0.1:11434', ollama_timeout_seconds=1,
        ollama_max_output_tokens=256, ollama_num_ctx=4096, ollama_keep_alive='1m',
        rag_top_k=6, rag_context_chars=2400, rag_query_embedding=True,
        rag_explanations=False, embedding_model='test-model')
    monkeypatch.setattr(pipeline, 'get_settings', lambda: settings)
    monkeypatch.setattr(pipeline, 'create_provider', lambda **kw: SimpleNamespace(name='qwen', model='synthetic'))
    for name in ('pause_embeddings', 'resume_embeddings', 'unload_ollama_model', 'verify_relevant_pending_statute'):
        if hasattr(pipeline, name): monkeypatch.setattr(pipeline, name, lambda *a, **k: None)
    calls = dict(fast=0, embed=0, full=0, generate=0)
    def fast(**kw):
        calls['fast'] += 1
        return try_fast_statute(**kw, loader=lambda *a: [statute()])
    async def embed(question):
        calls['embed'] += 1
        return None
    def full(*args, **kw):
        calls['full'] += 1
        return [statute()]
    def generate(*args, **kw):
        calls['generate'] += 1
        assert all(c.verification=='official' for c in kw['contexts'])
        if reject_fast_draft and calls['generate']==1:
            return 'Kaynaklarda yeterli bilgi bulunmuyor.'
        return TEXT + ' [K1]'
    monkeypatch.setattr(pipeline, 'try_fast_statute', fast)
    monkeypatch.setattr(pipeline, '_embed_question', embed)
    monkeypatch.setattr(pipeline, '_retrieve', full)
    monkeypatch.setattr(pipeline, 'generate_grounded_answer', generate)
    events=[]
    response, timings=asyncio.run(pipeline.execute_answer(AIAnswerRequest(question=QUESTION), None, on_stage=events.append))
    assert response.grounded and len([e for e in events if e['stage']=='done'])==1
    assert calls['fast']==1
    assert calls['embed']==calls['full']==int(reject_fast_draft)
    assert calls['generate']==1+int(reject_fast_draft)
    assert response.search_summary['research_deferred'] is not reject_fast_draft


def test_reinstatement_deadline_is_answered_from_the_current_statute_not_from_old_decisions():
    # Usul 2017'de değişti (önce arabulucu). Sözcük araması yalnız eski usulü anlatan 2015-2016 kararlarını getiriyordu.
    from api.ai.relevance import passage_relevant, question_intent

    for question in ("İşe iade davası açma süresi nedir?", "İşe iade için ne zaman başvurmam gerekir?", "İşe iade davası kaç gün içinde açılır?"):
        intent = question_intent(question)
        assert intent is not None and intent.statute == ("4857", "20"), question
        assert fast_reference(question) == ("4857", "20"), question
    # Süre sormayan işe iade sorusu bu maddeye kilitlenmez; içtihat isteyen soru hızlı yola girmez.
    assert question_intent("İşe iade davasında ispat yükü kimdedir?") is None
    assert fast_reference("İşe iade davası açma süresi hakkında Yargıtay kararları nelerdir?") is None

    question = "İşe iade davası açma süresi nedir?"
    mediation = "İş sözleşmesi feshedilen işçi, fesih bildiriminin tebliği tarihinden itibaren bir ay içinde işe iade talebiyle arabulucuya başvurmak zorundadır."
    lawsuit = "Arabuluculuk faaliyeti sonunda anlaşmaya varılamaması hâlinde, son tutanağın düzenlendiği tarihten itibaren, iki hafta içinde iş mahkemesinde dava açılabilir."
    burden = "Feshin geçerli bir sebebe dayandığını ispat yükümlülüğü işverene aittir."
    assert passage_relevant(question, mediation) and passage_relevant(question, lawsuit)
    assert not passage_relevant(question, burden)
