"""Post-check presentation must not erase a different source-approved rule."""
import pytest
import json

from api.ai.free_answer import _repeats, _free_verified_answer
from tests.factories import legislation_context
from tests.test_free_answer import Provider, verdict, with_parts


@pytest.mark.parametrize('first,second', [
    ('Başvuru süresi 30 gündür.', 'Başvuru süresi 60 gündür.'),
    ('İşçi bu haktan yararlanabilir.', 'İşçi bu haktan yararlanamaz.'),
    ('İşçi için en az altı aylık kıdem şartı aranır.', 'İşçi için en az altı aylık kıdem şartı aranmaz.'),
    ('Bu süre yazılı bildirimin yapıldığı gün başlar.', 'Bu süre yazılı bildirimin yapıldığı günü izleyen gün başlar.'),
    ('18 yaşında veya daha küçük işçiler için süre 20 gündür.', '18 yaşından küçük işçiler için süre 20 gündür.'),
    ('İşçinin yıllık izin süresi en az 14 gündür.', 'İşçinin yıllık izin süresi 4 gün artırılır.'),
    ('Koşul yaş >= 18 olmasıdır.', 'Koşul yaş <= 18 olmasıdır.'),
    ('Oran %1,5 olarak belirlenir.', 'Oran %1.5 olarak belirlenir.'),
])
def test_similar_words_are_not_proof_of_duplicate_information(first, second):
    assert not _repeats(second, [first])


def test_approved_duration_and_distinct_start_event_both_survive_with_complete_coverage():
    first = 'Başvuru süresi otuz gündür.'
    second = 'Başvuru süresi yazılı bildirimin yapıldığı günü izleyen gün başlar.'
    law = legislation_context(content=f'{first} {second}')
    provider = Provider(f'{first} @@ 1.1\n{second} @@ 1.2', with_parts(verdict(2), [[1], [2]]))
    info = {}
    answer = _free_verified_answer(provider, question='Süre ve başlangıcı?', contexts=[law], diagnostics=info,
        parts=[('Süre?', frozenset({law.chunk_id})), ('Başlangıç?', frozenset({law.chunk_id}))])
    assert answer is not None and first in answer.text and second in answer.text
    assert all(row['complete'] for row in info['final_part_coverage'])
    assert info.get('repeated_removed', 0) == 0


def test_checker_policy_preserves_necessary_conditions_without_turning_them_into_sufficient_ones():
    from api.ai.free_answer import LEAD_CHECK_INSTRUCTION
    assert 'sırf kaynak aynı olumsuz cümleyi yazmıyor diye reddetme' in LEAD_CHECK_INSTRUCTION
    assert 'Gerekli koşulu yeterli koşul sayma' in LEAD_CHECK_INSTRUCTION
    assert 'alternatif veya istisna varsa' in LEAD_CHECK_INSTRUCTION


def test_lossless_duplicate_does_not_spend_an_extra_write_and_check_attempt():
    from api.ai.free_answer import free_verified_answer
    rule = 'İşveren bildirim süresine uymazsa tazminat ödemek zorundadır.'
    law = legislation_context(content=rule)
    provider = Provider(f'{rule} @@ 1.1\n{rule} @@ 1.1', with_parts(verdict(2), [[1], [2]]))
    info = {}
    answer = free_verified_answer(provider, question='Tazminat koşulu?', contexts=[law], diagnostics=info,
        parts=[('İlk talep?', frozenset({law.chunk_id})), ('İkinci talep?', frozenset({law.chunk_id}))])
    assert answer is not None and len(provider.calls) == 2
    assert info['attempts'] == 1 and info['coverage_preserved'] is True
    assert info.get('partial_answer', False) is False


def test_same_words_with_distinct_source_bindings_are_not_merged():
    from dataclasses import replace
    from uuid import uuid4
    rule = 'İşveren bildirim süresine uymazsa tazminat ödemek zorundadır.'
    first = legislation_context(content=rule)
    second = replace(first, chunk_id=str(uuid4()), source_id=str(uuid4()))
    provider = Provider(f'{rule} @@ 1.1\n{rule} @@ 2.1', with_parts(verdict(2), [[1], [2]]))
    info = {}
    answer = _free_verified_answer(provider, question='İki kaynak?', contexts=[first, second], diagnostics=info,
        parts=[('İlk kaynak?', frozenset({first.chunk_id})), ('İkinci kaynak?', frozenset({second.chunk_id}))])
    assert answer is not None and len(answer.contexts) == 2
    assert all(row['complete'] for row in info['final_part_coverage'])
    assert not info.get('uncovered_parts')


def test_independently_confirmed_paraphrase_is_removed_without_losing_part_coverage():
    from tests.test_free_answer import LAW, RULE_1
    paraphrase = 'İşveren bildirim süresine uymazsa bu süreye ait ücret tutarındaki tazminatı ödemekle yükümlüdür.'
    check = json.loads(with_parts(verdict(2), [[1], [2]]))
    check['duplicate_claims'] = [{'id': 2, 'duplicate_of': 1}]
    provider = Provider(f'{RULE_1} @@ 1.1\n{paraphrase} @@ 1.1', json.dumps(check))
    info = {}
    answer = _free_verified_answer(provider, question='Bildirim ve tazminat?', contexts=[LAW], diagnostics=info,
        parts=[('Bildirim?', frozenset({LAW.chunk_id})), ('Tazminat?', frozenset({LAW.chunk_id}))])
    assert answer is not None and RULE_1 in answer.text and paraphrase not in answer.text
    assert info['semantic_repeated_removed'] == 1
    assert all(row['complete'] for row in info['final_part_coverage'])
    assert len(provider.calls) == 2


def test_semantic_duplicate_cannot_alias_a_rejected_claim():
    from tests.test_free_answer import LAW, RULE_1, RULE_2
    check = json.loads(verdict(2, approved={2}))
    check['duplicate_claims'] = [{'id': 2, 'duplicate_of': 1}]
    info = {}
    answer = _free_verified_answer(Provider(f'{RULE_1} @@ 1.1\n{RULE_2} @@ 1.2', json.dumps(check)),
        question='Bildirim süresi?', contexts=[LAW], diagnostics=info)
    assert answer is not None and RULE_2 in answer.text
    assert not info.get('semantic_repeated_removed')


def test_distinct_evidence_cannot_be_removed_by_semantic_duplicate_flag():
    from tests.test_free_answer import LAW, RULE_1, RULE_2
    check = json.loads(verdict(2))
    check['duplicate_claims'] = [{'id': 2, 'duplicate_of': 1}]
    info = {}
    answer = _free_verified_answer(Provider(f'{RULE_1} @@ 1.1\n{RULE_2} @@ 1.2', json.dumps(check)),
        question='Bildirim süresi?', contexts=[LAW], diagnostics=info)
    assert answer is not None and RULE_1 in answer.text and RULE_2 in answer.text
    assert not info.get('semantic_repeated_removed')


def test_cleaning_many_duplicates_is_not_a_substantial_information_loss_retry():
    from api.ai.free_answer import free_verified_answer
    from tests.test_free_answer import LAW, RULE_1
    provider = Provider('\n'.join(f'{RULE_1} @@ 1.1' for _ in range(8)), verdict(8))
    info = {}
    answer = free_verified_answer(provider, question='Bildirim tazminatı?', contexts=[LAW], diagnostics=info)
    assert answer is not None and answer.text.count(RULE_1) == 1
    assert info['repeated_removed'] == 7
    assert info['attempts'] == 1 and len(provider.calls) == 2


@pytest.mark.parametrize('first,second', [
    ('Süre 30 gündür.', 'Süre 60 gündür.'),
    ('Süre 2 haftadır.', 'Süre 2 aydır.'),
    ('En az 18 yaş gerekir.', 'En fazla 18 yaş gerekir.'),
])
def test_semantic_duplicate_flag_cannot_erase_distinct_numeric_rules(first, second):
    law = legislation_context(content=f'{first} {second}')
    check = json.loads(verdict(2))
    check['duplicate_claims'] = [{'id': 2, 'duplicate_of': 1}]
    info = {}
    answer = _free_verified_answer(
        Provider(f'{first} @@ 1.1 1.2\n{second} @@ 1.1 1.2', json.dumps(check)),
        question='Süre ve koşullar?', contexts=[law], diagnostics=info,
    )
    assert answer is not None and first in answer.text and second in answer.text
    assert not info.get('semantic_repeated_removed')


def test_duplicate_chain_resolves_only_to_an_actually_displayed_approved_claim():
    from tests.test_free_answer import LAW, RULE_1
    second = 'İşveren bildirim süresine uymazsa bu süreye ait ücret tutarındaki tazminatı ödemekle yükümlüdür.'
    third = 'Bildirim süresine uymayan işveren, bu süreye ait ücret tutarında tazminat ödemek zorundadır.'
    check = json.loads(verdict(3))
    check['duplicate_claims'] = [{'id': 2, 'duplicate_of': 1}, {'id': 3, 'duplicate_of': 2}]
    info = {}
    answer = _free_verified_answer(
        Provider(f'{RULE_1} @@ 1.1\n{second} @@ 1.1\n{third} @@ 1.1', json.dumps(check)),
        question='Bildirim tazminatı?', contexts=[LAW], diagnostics=info)
    assert answer is not None and answer.text == RULE_1
    assert info['semantic_repeated_removed'] == 2
