import json

import httpx
import pytest

from api.ai.local_synthesis_schema import synthesis_schema
from api.ai.providers import OllamaProvider
from api.ai import synthesis
from tests.factories import legislation_context


def test_fixed_local_checker_keys_preserve_nonconsecutive_ids_and_false_verdicts():
    from api.ai.local_synthesis_schema import fixed_checker_schema, unpack_fixed_verdict
    payload = {'claims': [{'id': 2}, {'id': 7}]}
    schema = fixed_checker_schema(payload)
    assert schema['properties']['claims']['required'] == ['2', '7']
    value = {'claims': {str(i): {'supported': False, 'relevant': True, 'scope_preserved': False}
                        for i in (2, 7)}, 'coverage_preserved': False,
             'source_only': True, 'clarification_safe': True}
    result = json.loads(unpack_fixed_verdict(json.dumps(value), payload))
    assert [claim['id'] for claim in result['claims']] == [2, 7]
    assert all(claim['supported'] is False for claim in result['claims'])
    assert result['coverage_preserved'] is False


@pytest.mark.parametrize('claims', [
    {'1': {'supported': True, 'relevant': True, 'scope_preserved': True}},
    {'2': {'supported': 'false', 'relevant': True, 'scope_preserved': True}},
    {'2': {'supported': True, 'relevant': True}},
    {},
])
def test_fixed_local_checker_never_repairs_missing_wrong_or_truthy_flags(claims):
    from api.ai.local_synthesis_schema import unpack_fixed_verdict
    with pytest.raises(ValueError):
        unpack_fixed_verdict(json.dumps({'claims': claims}), {'claims': [{'id': 2}]})


def test_fixed_local_checker_duplicate_json_keys_are_rejected():
    from api.ai.local_synthesis_schema import unpack_fixed_verdict
    with pytest.raises(ValueError):
        unpack_fixed_verdict('{"claims":{"2":{},"2":{}}}', {'claims': [{'id': 2}]})


@pytest.mark.parametrize('supported', [True, False])
def test_local_synthesis_fixed_wire_contract_keeps_independent_semantic_decision(supported):
    from api.ai.local_synthesis_schema import LOCAL_WRITE_INSTRUCTION
    law = legislation_context(content='Başvuru yazılı yapılır.')
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            assert body['messages'][0]['content'].startswith(LOCAL_WRITE_INSTRUCTION)
            value = {'claims': [{'text': law.content, 'evidence': [{'source': 1, 'unit': 1}]}],
                     'question': None, 'source_gap': False}
        else:
            assert body['format']['properties']['claims']['required'] == ['1']
            value = {'claims': {'1': {'supported': supported, 'relevant': True,
                                     'scope_preserved': supported}},
                     'coverage_preserved': supported, 'source_only': True,
                     'clarification_safe': True}
        return httpx.Response(200, json={'message': {'content': json.dumps(value)}})
    provider = OllamaProvider(model='qwen3.5:4b', transport=httpx.MockTransport(handler))
    result = synthesis.synthesize_answer(provider, question='Başvuru nasıl yapılır?',
        contexts=[law], compact_evidence=True, repair_attempts=0)
    assert (result is not None) is supported
    assert len(calls) == 2


def test_writer_schema_requires_units_from_the_actual_source_not_free_quotes():
    schema = synthesis_schema('draft', {'sources': [
        {'source': 2, 'evidence_units': [{'unit': 3, 'text': 'rule'}]}]})
    assert set(schema['required']) == {'claims', 'question', 'source_gap'}
    claim = schema['properties']['claims']['items']
    assert set(claim['required']) == {'text', 'evidence'}
    evidence = claim['properties']['evidence']['items']['anyOf'][0]
    assert evidence['properties']['source']['enum'] == [2]
    assert evidence['properties']['unit']['enum'] == [3]
    assert evidence['additionalProperties'] is False


@pytest.mark.parametrize('count', [0, 1, 3])
def test_checker_schema_cannot_generate_verdicts_for_nonexistent_claims(count):
    schema = synthesis_schema('check', {'claims': [{'id': i} for i in range(1, count + 1)]})
    claims = schema['properties']['claims']
    assert claims['minItems'] == count == claims['maxItems']
    assert schema['properties']['source_only'] == {'type': 'boolean'}
    if count:
        assert claims['items']['properties']['id']['enum'] == list(range(1, count + 1))


def test_structured_provider_sends_native_format_without_weakening_verdict_checks():
    schema = synthesis_schema('check', {'claims': [{'id': 1}]})
    raw = json.dumps({'claims': [{'id': 1, 'supported': False, 'relevant': True, 'scope_preserved': False}],
                      'coverage_preserved': False, 'source_only': True, 'clarification_safe': True})
    def handler(request):
        body = json.loads(request.content)
        assert body['format'] == schema and body['think'] is False
        return httpx.Response(200, json={'message': {'content': raw}})
    provider = OllamaProvider(model='qwen3.5:4b', transport=httpx.MockTransport(handler))
    result = provider.generate_structured(system_instruction='test', prompt='test', schema=schema)
    assert not synthesis._approved(result, 1)


def test_structured_unit_indices_still_pass_through_exact_source_resolution():
    law = legislation_context(content='Başvuru yazılı yapılır.')
    views = synthesis._source_views([law], 4000)
    raw = json.dumps({'claims': [{'text': 'Başvuru yazılı yapılır.', 'evidence': [{'source': 1, 'unit': 999}]}],
                      'question': None, 'source_gap': False})
    with pytest.raises((ValueError, TypeError, KeyError)):
        synthesis._parse_draft(raw, [law], views)


def test_local_qwen_natural_answer_uses_native_units_and_an_independent_checker():
    from api.ai.free_answer import _free_verified_answer
    from tests.test_free_answer import LAW, RULE_1, verdict
    calls = []
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert isinstance(body['format'], dict)
        if len(calls) == 1:
            payload = json.loads(body['messages'][1]['content'])
            assert payload['sources'][0]['evidence_units']
            value = {'claims': [{'text': RULE_1, 'evidence': [{'source': 1, 'unit': 1}]}],
                     'question': None, 'source_gap': False}
            raw = json.dumps(value)
        else:
            assert body['format']['properties']['claims']['maxItems'] == 1
            raw = verdict(1)
        return httpx.Response(200, json={'message': {'content': raw}})
    provider = OllamaProvider(model='qwen3.5:4b', num_ctx=8192, max_output_tokens=2048,
                              transport=httpx.MockTransport(handler))
    answer = _free_verified_answer(provider, question='Bildirim tazminatı?', contexts=[LAW])
    assert answer is not None and answer.text == RULE_1
    assert len(calls) == 2


def test_local_qwen_cannot_publish_a_structurally_valid_but_rejected_claim():
    from api.ai.free_answer import _free_verified_answer
    from tests.test_free_answer import LAW, RULE_1, verdict
    responses = [json.dumps({'claims': [{'text': RULE_1, 'evidence': [{'source': 1, 'unit': 1}]}],
                            'question': None, 'source_gap': False}), verdict(1, approved=set())]
    provider = OllamaProvider(model='qwen3.5:4b', num_ctx=8192, max_output_tokens=2048,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'message': {'content': responses.pop(0)}})))
    assert _free_verified_answer(provider, question='Bildirim tazminatı?', contexts=[LAW]) is None


def test_local_checker_schema_retains_every_question_part():
    schema = synthesis_schema('check', {'claims': [{'id': 1}], 'question_parts': ['A?', 'B?']})
    parts = schema['properties']['part_coverage']
    assert parts['minItems'] == parts['maxItems'] == 2
    assert parts['items']['properties']['part_id']['enum'] == [1, 2]
