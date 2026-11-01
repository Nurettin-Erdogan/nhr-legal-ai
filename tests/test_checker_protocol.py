import json

import pytest

from api.ai.checker_protocol import check_claims, verdict_status
from api.ai.free_answer import free_verified_answer
from api.ai.providers import AIProviderError
from tests.test_free_answer import Provider, LAW, DECISION, DRAFT, verdict


def valid():
    return json.loads(verdict(1))


@pytest.mark.parametrize('flag', ['source_only', 'clarification_safe', 'coverage_preserved'])
@pytest.mark.parametrize('wrong', ['true', 'false', 1, 0, None, [], {}])
def test_global_flags_are_never_coerced(flag, wrong):
    value = valid()
    value[flag] = wrong
    assert verdict_status(json.dumps(value), 1) == 'invalid_global_boolean'


@pytest.mark.parametrize('flag', ['supported', 'relevant', 'scope_preserved'])
@pytest.mark.parametrize('wrong', ['true', 'false', 1, 0, None])
def test_claim_flags_are_never_coerced(flag, wrong):
    value = valid()
    value['claims'][0][flag] = wrong
    assert verdict_status(json.dumps(value), 1) == 'invalid_claim_fields_or_ids'


def test_schema_diagnostics_separate_policy_rejections_from_protocol_errors():
    assert verdict_status('not JSON', 1) == 'invalid_json'
    assert verdict_status('{}', 1) == 'invalid_top_level_fields'
    assert verdict_status(verdict(0), 1) == 'invalid_claim_count'
    value = valid()
    value['source_only'] = False
    assert verdict_status(json.dumps(value), 1) == 'source_policy_rejected'
    value = valid()
    value['clarification_safe'] = False
    assert verdict_status(json.dumps(value), 1) == 'clarification_rejected'
    assert verdict_status(verdict(1, approved=set()), 1) == 'valid'


def test_duplicate_missing_and_out_of_range_ids_remain_invalid():
    value = json.loads(verdict(2))
    value['claims'][1]['id'] = 1
    assert verdict_status(json.dumps(value), 2) == 'invalid_claim_fields_or_ids'
    value['claims'][1]['id'] = 3
    assert verdict_status(json.dumps(value), 2) == 'invalid_claim_fields_or_ids'
    value['claims'][1]['id'] = True
    assert verdict_status(json.dumps(value), 2) == 'invalid_claim_fields_or_ids'


def test_format_recovery_rechecks_identical_payload_and_does_not_rewrite_answer():
    provider = Provider(DRAFT, '{}', verdict(3))
    info = {}
    result = free_verified_answer(provider, question='Bildirim süresine uyulmazsa ne olur?',
                                 contexts=[LAW, DECISION], diagnostics=info)
    assert result is not None
    assert len(provider.calls) == 3
    assert provider.calls[1]['prompt'] == provider.calls[2]['prompt']
    assert info['attempts'] == 1
    assert info['checker_protocol_attempts'] == ['invalid_top_level_fields', 'valid']


def test_repeated_protocol_failure_does_not_rewrite_or_publish():
    provider = Provider(DRAFT, '{}', '{}')
    info = {}
    assert free_verified_answer(provider, question='Bildirim süresine uyulmazsa ne olur?',
                                contexts=[LAW, DECISION], diagnostics=info) is None
    assert info['reason'] == 'checker_protocol'
    assert len(provider.calls) == 3 and info['attempts'] == 1


def test_recovery_is_never_an_approval_override_or_extra_writer_retry():
    provider = Provider(DRAFT, '{}', verdict(3, approved=set()))
    info = {}
    assert free_verified_answer(provider, question='Bildirim süresine uyulmazsa ne olur?',
                                contexts=[LAW, DECISION], diagnostics=info) is None
    assert info['reason'] == 'checker' and len(provider.calls) == 3


@pytest.mark.parametrize('flag', ['source_only', 'clarification_safe'])
def test_well_formed_policy_refusal_is_not_retried_as_format(flag):
    value = valid()
    value[flag] = False
    provider = Provider(json.dumps(value))
    info = {}
    raw = check_claims(provider, instruction='test', payload={'claims': [{'id': 1}]},
                       allow_format_retry=True, diagnostics=info)
    assert json.loads(raw)[flag] is False
    assert len(provider.calls) == 1 and info['checker_protocol_retries'] == 0


def test_diagnostics_do_not_contain_prompts_sources_or_raw_responses():
    provider = Provider('{}', verdict(1))
    info = {}
    check_claims(provider, instruction='secret instruction',
                 payload={'claims': [{'id': 1, 'text': 'private user text'}]},
                 allow_format_retry=True, diagnostics=info)
    assert 'private' not in json.dumps(info) and 'secret' not in json.dumps(info)
    assert set(info) == {'checker_protocol_status', 'checker_protocol_attempts', 'checker_protocol_retries'}


def test_provider_error_is_not_treated_as_a_malformed_approval():
    class Broken:
        def generate(self, **kwargs):
            raise AIProviderError('service failed')
    with pytest.raises(AIProviderError):
        check_claims(Broken(), instruction='test', payload={'claims': []}, allow_format_retry=True)


@pytest.mark.parametrize('flag', ['source_only', 'clarification_safe'])
def test_multipart_policy_refusal_is_not_misreported_as_missing_coverage(flag):
    from api.ai.free_answer import _free_verified_answer
    from tests.test_free_answer import with_parts

    value = json.loads(with_parts(verdict(3), [[1, 2], [3]]))
    value[flag] = False
    provider = Provider(DRAFT, json.dumps(value))
    info = {}
    result = _free_verified_answer(
        provider, question='Tazminat ve karar?', contexts=[LAW, DECISION], diagnostics=info,
        parts=[('Tazminat?', frozenset({LAW.chunk_id})),
               ('Karar?', frozenset({DECISION.chunk_id}))],
    )
    assert result is None
    assert info['reason'] == 'checker'
    assert info['checker_status'] == (
        'source_policy_rejected' if flag == 'source_only' else 'clarification_rejected'
    )
    assert len(provider.calls) == 2


@pytest.mark.parametrize('entries', [None, {}, [{'id': True, 'duplicate_of': 1}],
    [{'id': 1, 'duplicate_of': 1}], [{'id': 2, 'duplicate_of': 3}],
    [{'id': 3, 'duplicate_of': 1}], [{'id': 2, 'duplicate_of': 1, 'extra': True}],
    [{'id': 2, 'duplicate_of': 1}, {'id': 2, 'duplicate_of': 1}]])
def test_invalid_duplicate_map_never_authorizes_a_verdict(entries):
    from api.ai import synthesis
    value = json.loads(verdict(2))
    value['duplicate_claims'] = entries
    info = {}
    raw = check_claims(Provider(json.dumps(value)), instruction='test',
        payload={'claims': [{'id': 1}, {'id': 2}]}, diagnostics=info)
    assert synthesis._fully_approved_ids(raw, 2) is None
    assert not info.get('checker_duplicates')
