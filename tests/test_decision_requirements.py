from dataclasses import replace
import pytest

from api.ai.decision_requirements import distinct_decisions, requested_decision_count
from api.ai.evidence_readiness import requested_decisions_ready
from api.ai.free_answer import _free_verified_answer
from tests.factories import court_decision_context
from tests.test_free_answer import Provider, LAW, RULE_1, verdict


@pytest.mark.parametrize('question,count', [
    ('Konuyla doğrudan ilgili iki gerçek Yargıtay kararını göster.', 2),
    ('Üç farklı Danıştay kararı göster.', 3),
    ('2 ayrı doğrulanabilir Yargıtay kararını getir.', 2),
    ('İki yıldır çalışıyorum, Yargıtay kararları ne diyor?', 1),
    ('30 işçi şartını iki karar ile açıkla.', 2),
    ('4857 sayılı Kanunun 18. maddesi?', 0),
])
def test_explicit_cardinality_is_not_a_case_fact(question, count):
    assert requested_decision_count(question) == count


def test_duplicate_record_ids_do_not_make_two_judgments():
    first = court_decision_context()
    duplicate = replace(first, source_id=LAW.source_id, chunk_id=LAW.chunk_id)
    assert distinct_decisions('İki Yargıtay kararı', [first, duplicate]) == 1
    assert not requested_decisions_ready('İki gerçek Yargıtay kararı', [first, duplicate])
    second = replace(duplicate, decision_no='2026/3')
    assert requested_decisions_ready('İki gerçek Yargıtay kararı', [first, second])


def test_another_requested_court_is_not_counted_as_yargitay():
    first = court_decision_context()
    other = replace(first, court_name='Danıştay', chamber='4. Daire', decision_no='2026/3')
    assert distinct_decisions('İki Yargıtay kararı', [first, other]) == 1


def test_sources_in_pool_are_not_the_same_as_sources_used_in_final_answer():
    first = court_decision_context()
    second = replace(first, source_id=LAW.source_id, chunk_id=LAW.chunk_id, decision_no='2026/3')
    # Even a positive model coverage verdict cannot convert an unused second
    # decision into an answered request. No extra paid call is needed for this.
    info = {}
    answer = _free_verified_answer(
        Provider(f'{RULE_1} @@ 1.1', verdict(1)),
        question='İki gerçek Yargıtay kararını göster.', contexts=[LAW, first, second], diagnostics=info,
    )
    assert answer is not None
    assert info['decision_coverage'] == dict(requested=2, cited=0, complete=False)
    assert info['coverage_preserved'] is False and info['partial_answer']
