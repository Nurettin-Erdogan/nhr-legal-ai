from dataclasses import replace

from api.ai.evidence_pool import balanced_evidence
from tests.factories import legislation_context


def context(number):
    return legislation_context(chunk_id=f"00000000-0000-0000-0000-{number:012d}",
                               source_id=f"00000000-0000-0000-0001-{number:012d}")


def test_other_query_is_not_starved_by_first_query_hints():
    a, b, c, d = [context(i) for i in range(1, 5)]
    assert balanced_evidence([[a, b, c], [d]], 3) == [a, d, b]


def test_deduplicate_chunks_and_exclude_unverified_sources():
    a, b = context(1), context(2)
    pending = replace(context(3), verification="third_party")
    assert balanced_evidence([[a, pending], [a, b]], 6) == [a, b]


def test_empty_lanes():
    assert balanced_evidence([[], []], 6) == []
    assert balanced_evidence([[context(1)]], 0) == []


def test_explicit_law_scopes_only_its_query_lane_not_decisions_or_independent_facets():
    from api.ai.evidence_pool import query_scoped_evidence
    from tests.factories import legislation_context, court_decision_context
    from dataclasses import replace
    law = legislation_context()
    other = replace(law, law_no='5362')
    decision = court_decision_context()
    rows = [law, other, decision]
    assert query_scoped_evidence('4857 sayılı İş Kanunu işe iade koşulları', rows) == [law, decision]
    assert query_scoped_evidence('İşe iade koşulları', rows) == rows
    assert query_scoped_evidence('4857 ve 5362 sayılı kanunlar', rows) == rows


def test_one_long_article_cannot_consume_all_slots_before_another_article():
    a, b, c = context(1), context(2), context(3)
    b = replace(b, source_id=a.source_id)
    assert balanced_evidence([[a, b, c]], 2) == [a, c]


def test_court_constraints_run_before_bounded_slot_selection():
    from api.ai.evidence_pool import query_scoped_evidence
    from tests.factories import court_decision_context
    wrong = replace(court_decision_context(content='Kira artışı incelenmiştir.'),
                    court_name='İstanbul Bölge Adliye Mahkemesi')
    right = replace(wrong, chunk_id=context(90).chunk_id, source_id=context(90).source_id, court_name='Yargıtay')
    lane = query_scoped_evidence('Kira artışına ilişkin Yargıtay kararları', [wrong, right])
    assert balanced_evidence([lane], 1) == [right]


def test_weak_metadata_match_does_not_starve_actual_text_in_query_lane():
    from api.ai.evidence_pool import query_scoped_evidence
    irrelevant = replace(context(91), law_no='5362', content='Esnaf siciline tescil usulü düzenlenir.')
    relevant = replace(context(92), law_no='6098', article_no='344',
                        content='Kira artışı tüketici fiyat endeksine göre belirlenir.')
    source = [irrelevant, relevant]
    ranked = query_scoped_evidence('Kira artışı nasıl belirlenir?', source)
    assert ranked == [relevant, irrelevant]
    assert balanced_evidence([ranked], 1) == [relevant]
    assert source == [irrelevant, relevant]
