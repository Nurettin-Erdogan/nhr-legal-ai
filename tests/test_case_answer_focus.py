from dataclasses import replace
from uuid import UUID

from api.ai.decision_attribution import irrelevant_case_filler, with_case_identity
from tests.factories import court_decision_context
from tests.test_free_answer import LAW, DECISION, RULE_1, Provider, verdict
from api.ai.free_answer import free_verified_answer


def test_observed_irrelevant_case_anecdote_is_not_answer_evidence():
    text = ('Yargıtay süreyi değerlendirmiştir; bu karar süreye ilişkindir, '
            'ihtarda fesih bildirimi bulunması hakkında bir değerlendirme içermez.')
    assert irrelevant_case_filler(text, 'İhtarda fesih bildirimi yoksa geçerli midir?')
    assert not irrelevant_case_filler(text, 'Bu karar olayımızla ilgili mi?')
    assert not irrelevant_case_filler(text, 'Bu karar ile diğer kararı karşılaştır.')


def test_case_limits_are_not_all_removed_as_filler():
    assert not irrelevant_case_filler('Yargıtay bu kararda ödeme süresini değerlendirmiştir.',
                                      'Ödeme süresiyle ilgili kararları açıkla.')
    assert not irrelevant_case_filler('Bu karar, fesih bildiriminin gerekli olduğunu belirtir.',
                                      'Fesih bildirimi gerekir mi?')


def test_identity_comes_only_from_one_verified_cited_case():
    source = replace(court_decision_context(), court_name='Yargıtay', docket_no='2018/12', decision_no='2018/34')
    claim = 'Yargıtay bildirim süresini değerlendirmiştir.'
    shown = with_case_identity(claim, [(1, 'kanıt')], [source])
    assert shown == claim + ' (E. 2018/12, K. 2018/34)'
    assert with_case_identity(shown, [(1, 'kanıt')], [source]) == shown
    assert with_case_identity(claim, [(1, 'kanıt')], [replace(source, verification='third_party')]) == claim
    assert with_case_identity(claim, [(1, 'kanıt')], [replace(source, docket_no=None)]) == claim
    other = replace(source, source_id=UUID(int=666), docket_no='2020/1')
    assert with_case_identity(claim, [(1, 'kanıt'), (2, 'kanıt')], [source, other]) == claim


def test_identity_does_not_change_anonymous_or_legislation_claim():
    source = replace(court_decision_context(), court_name='Yargıtay')
    assert with_case_identity('Bildirim süresi değerlendirilmiştir.', [(1, 'kanıt')], [source]) == 'Bildirim süresi değerlendirilmiştir.'
    assert with_case_identity('Yargıtay değerlendirmiştir.', [(1, 'kanıt')], [LAW]) == 'Yargıtay değerlendirmiştir.'


def test_filler_cannot_be_published_even_with_always_approving_checker():
    filler = ('Yargıtay bildirim süresini incelemiştir; bu karar sorulan meseleyi '
              'ele almıyor.')
    draft = RULE_1 + ' @@ 1.1\n\n' + filler + ' @@ 2.2'
    provider = Provider(draft, verdict(1))
    diagnostics = {}
    result = free_verified_answer(provider, question='Bildirim süresine uyulmazsa ne olur?',
        contexts=[LAW, DECISION], diagnostics=diagnostics)
    assert result is not None
    assert 'ele almıyor' not in result.text
    assert 'irrelevant_case_filler' in diagnostics['sentence_outcomes']['2']
    assert 'Yargıtay' not in result.text
