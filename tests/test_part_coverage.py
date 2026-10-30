"""Coverage bookkeeping tests, not proof of a model's semantic judgment."""
import json

import pytest

from api.ai import free_answer
from api.ai.checker_protocol import check_claims
from api.ai.part_coverage import INSTRUCTION, final_coverage, split_verdict
from tests.test_free_answer import Provider, LAW, RULE_1, RULE_2, verdict, with_parts


def test_one_shared_source_does_not_answer_two_parts():
    provider = Provider(f'{RULE_1} @@ 1.1', with_parts(verdict(1), [[1], []]))
    info = {}
    answer = free_answer._free_verified_answer(provider, question='Tazminat ve süre?', contexts=[LAW],
        diagnostics=info, parts=[('Tazminat hakkı?', frozenset({LAW.chunk_id})),
                                ('Bildirim süresi?', frozenset({LAW.chunk_id}))])
    assert answer is not None
    assert info['final_part_coverage'][0]['complete'] is True
    assert info['final_part_coverage'][1]['complete'] is False
    assert info['incomplete_parts'] == ['Bildirim süresi?']
    assert info['coverage_preserved'] is False and info['partial_answer']
    assert len(provider.calls) == 2


def test_rejected_sentence_cannot_count_as_an_answer_even_when_source_is_shared():
    provider = Provider(f'{RULE_1} @@ 1.1\n{RULE_2} @@ 1.2',
                        with_parts(verdict(2, approved={1}), [[1], [2]]))
    info = {}
    answer = free_answer._free_verified_answer(provider, question='Tazminat ve süre?', contexts=[LAW],
        diagnostics=info, parts=[('Tazminat hakkı?', frozenset({LAW.chunk_id})),
                                ('Bildirim süresi?', frozenset({LAW.chunk_id}))])
    assert answer is not None and RULE_2 not in answer.text
    assert info['final_part_coverage'][1]['displayed_sentence_ids'] == []
    assert info['final_part_coverage'][1]['complete'] is False


def test_coverage_uses_displayed_original_ids_not_candidate_or_source_ids():
    rows = [{'part_id': 1, 'claim_ids': [1], 'complete': True, 'why': ''},
            {'part_id': 2, 'claim_ids': [2], 'complete': True, 'why': ''}]
    result = final_coverage(rows, {1: 3, 2: 7}, {3})
    assert result[0]['complete'] is True and result[0]['displayed_sentence_ids'] == [3]
    assert result[1]['complete'] is False


def test_exact_duplicate_uses_the_already_displayed_approved_sentence_for_coverage():
    provider = Provider(f'{RULE_1} @@ 1.1\n{RULE_1} @@ 1.1', with_parts(verdict(2), [[1], [2]]))
    info = {}
    free_answer._free_verified_answer(provider, question='İki ayrı parça?', contexts=[LAW], diagnostics=info,
        parts=[('Birinci parça?', frozenset({LAW.chunk_id})), ('İkinci parça?', frozenset({LAW.chunk_id}))])
    assert info['repeated_removed'] == 1 and info['kept'] == 1
    assert info['final_part_coverage'][1]['complete'] is True
    assert info['final_part_coverage'][1]['displayed_sentence_ids'] == [1]


def test_duplicate_alias_cannot_count_when_its_target_was_not_displayed():
    rows = [{'part_id': 1, 'claim_ids': [1], 'complete': True, 'why': ''}]
    assert final_coverage(rows, {1: 7}, {3}, duplicate_aliases={7: 9})[0]['complete'] is False


def test_missing_part_map_is_a_protocol_failure_not_a_legacy_approval():
    provider = Provider(f'{RULE_1} @@ 1.1', verdict(1))
    info = {}
    result = free_answer._free_verified_answer(provider, question='İki ayrı parça?', contexts=[LAW], diagnostics=info,
        parts=[('Birinci parça?', frozenset({LAW.chunk_id})), ('İkinci parça?', frozenset({LAW.chunk_id}))])
    assert result is None and info['reason'] == 'checker_protocol'


@pytest.mark.parametrize('ids', [[True], ['1'], [0], [3], [1, 1]])
def test_invalid_claim_ids_never_become_coverage(ids):
    raw = json.loads(with_parts(verdict(2), [[1], [2]]))
    raw['part_coverage'][0]['claim_ids'] = ids
    with pytest.raises(ValueError):
        split_verdict(json.dumps(raw), 2, 2)


@pytest.mark.parametrize('wrong', ['true', 1, None])
def test_coverage_booleans_are_not_coerced(wrong):
    raw = json.loads(with_parts(verdict(2), [[1], [2]]))
    raw['part_coverage'][0]['complete'] = wrong
    with pytest.raises(ValueError):
        split_verdict(json.dumps(raw), 2, 2)


def test_missing_or_duplicate_parts_and_empty_complete_are_invalid():
    original = json.loads(with_parts(verdict(2), [[1], [2]]))
    for modify in ('missing', 'duplicate', 'empty'):
        raw = json.loads(json.dumps(original))
        if modify == 'missing':
            raw['part_coverage'].pop()
        elif modify == 'duplicate':
            raw['part_coverage'][1]['part_id'] = 1
        else:
            raw['part_coverage'][0]['claim_ids'] = []
        with pytest.raises(ValueError):
            split_verdict(json.dumps(raw), 2, 2)


def test_format_retry_keeps_same_evidence_and_requires_part_map():
    provider = Provider(verdict(1), with_parts(verdict(1), [[1], []]))
    info = {}
    result = check_claims(provider, instruction=INSTRUCTION,
        payload={'claims': [{'id': 1}], 'question_parts': ['one', 'two']},
        part_count=2, allow_format_retry=True, diagnostics=info)
    assert json.loads(result)['coverage_preserved'] is True
    assert info['checker_protocol_attempts'] == ['invalid_part_coverage', 'valid']
    assert provider.calls[0]['prompt'] == provider.calls[1]['prompt']
    assert len(info['checker_part_coverage']) == 2


def test_only_missing_part_is_repaired_without_an_extra_checker_call():
    provider = Provider(f'{RULE_1} @@ 1.1', with_parts(verdict(1), [[1], []]),
                        f'{RULE_2} @@ 1.2', with_parts(verdict(2), [[1], [2]]))
    info = {}
    answer = free_answer.free_verified_answer(provider, question='Tazminat ve süre?', contexts=[LAW],
        diagnostics=info, parts=[('Tazminat hakkı?', frozenset({LAW.chunk_id})),
                                ('Bildirim süresi?', frozenset({LAW.chunk_id}))])
    assert answer is not None and RULE_1 in answer.text and RULE_2 in answer.text
    repair = json.loads(provider.calls[2]['prompt'])
    assert repair['revision_feedback_not_evidence']['incomplete_parts'] == ['Bildirim süresi?']
    assert info['coverage_preserved'] is True
    assert all(row['complete'] for row in info['final_part_coverage'])
    assert len(provider.calls) == 4


def test_part_map_cannot_override_negative_global_coverage():
    raw = json.loads(with_parts(verdict(1), [[1], [1]]))
    raw['coverage_preserved'] = False
    info = {}
    free_answer._free_verified_answer(Provider(f'{RULE_1} @@ 1.1', json.dumps(raw)),
        question='İki parça?', contexts=[LAW], diagnostics=info,
        parts=[('Birinci parça?', frozenset({LAW.chunk_id})), ('İkinci parça?', frozenset({LAW.chunk_id}))])
    assert info['coverage_preserved'] is False


def test_provider_schema_requires_the_part_map_without_changing_plain_checker_contract():
    from api.ai.cloud_provider import create_cloud_provider
    provider = create_cloud_provider(provider_name='openrouter', model='openai/gpt-6-luna', api_key='fixture')
    normal = provider._json_response_format(free_answer.LEAD_CHECK_INSTRUCTION)['json_schema']['schema']
    extended = provider._json_response_format(free_answer.LEAD_CHECK_INSTRUCTION + INSTRUCTION)['json_schema']['schema']
    assert 'part_coverage' not in normal['properties']
    assert 'part_coverage' in extended['required']
    item = extended['properties']['part_coverage']['items']
    assert item['additionalProperties'] is False
    assert set(item['required']) == set(item['properties'])
