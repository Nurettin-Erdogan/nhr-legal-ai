from dataclasses import replace

from api.ai.chat_research_policy import official_research_reasons
from tests.factories import legislation_context, court_decision_context


def reasons(question, rows, *, usable=lambda c: True, relevant=lambda q, c: True):
    return official_research_reasons(question, [(question, (question,))], rows,
                                     usable=usable, relevant=relevant)


def test_ready_local_rule_does_not_force_a_portal_request():
    assert reasons('Kira artışı nasıl belirlenir?', [legislation_context()]) == ()


def test_freshness_explicitly_requested_still_uses_official_research():
    assert reasons('2026 yılı itibarıyla güncel kira kuralı?', [legislation_context()]) == ('freshness_requested',)


def test_private_or_historical_dates_are_not_assumed_to_request_current_news():
    assert reasons('2018 yılında evlendik, ev nasıl paylaşılır?', [legislation_context()]) == ()


def test_missing_unusable_and_irrelevant_evidence_each_keep_web_lane_open():
    law = legislation_context()
    assert reasons('Kira artışı?', [])
    assert reasons('Kira artışı?', [law], usable=lambda c: False)
    assert reasons('Kira artışı?', [law], relevant=lambda q, c: False)


def test_two_requested_court_sources_cannot_be_replaced_by_one_or_other_court():
    a = court_decision_context(content='İşe iade koşulları değerlendirilmiştir.')
    b = replace(a, chunk_id=legislation_context().chunk_id, source_id=legislation_context().source_id,
                decision_no='2026/3')
    question = 'İki Yargıtay kararını göster'
    assert reasons(question, [a, legislation_context()])
    assert reasons(question, [a, replace(b, court_name='Danıştay')])
    assert reasons(question, [a, b]) == ()


def test_each_subquestion_needs_relevant_evidence():
    law = legislation_context()
    actual = official_research_reasons('İki ayrı konu', [('A', ('a',)), ('B', ('b',))], [law],
        usable=lambda c: True, relevant=lambda q, c: q in ('A', 'a'))
    assert actual == ('part_2_source_gap',)
