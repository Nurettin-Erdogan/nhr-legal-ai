import pytest
from api.ai.search_plan import plan_search, research_queries
from api.ai.official_research import safe_topics


@pytest.mark.parametrize('concept', ['muris muvazaası', 'işe iade', 'ortak velayet',
    'kıdem tazminatı', 'itirazın iptali'])
def test_research_instructions_do_not_replace_independent_concept_search(concept):
    question = concept + ' deliller ve değerlendirme ölçütlerini açıkla'
    assert plan_search(question).phrase == concept
    assert research_queries(question) == (question, concept)


def test_simple_concept_does_not_duplicate_queries():
    assert research_queries('muris muvazaası') == ('muris muvazaası',)
    assert research_queries('belirli olmayan bir konu') == ('belirli olmayan bir konu',)


def test_tbk_315_case_law_request_gets_compact_local_search_lane():
    question = "Kirac\u0131ya 30 g\u00fcn s\u00fcre verdim. TBK m.315'e g\u00f6re ihtar ge\u00e7erli mi? \u0130lgili Yarg\u0131tay kararlar\u0131yla a\u00e7\u0131kla."
    queries = research_queries(question)
    assert queries[0] == question
    assert "TBK 315 temerrüt fesih" in queries


def test_tbk_315_without_case_law_request_keeps_original_search_only():
    question = "TBK m.315 ne düzenler?"
    assert research_queries(question) == (question,)


def test_public_portal_search_prefers_specific_legal_concept_not_personal_facts():
    topics = safe_topics('Ahmet 250000 TL muris muvazaası miras tapu delilleri')
    assert topics[0] == 'muris muvazaası'
    assert all('Ahmet' not in topic and '250000' not in topic for topic in topics)
