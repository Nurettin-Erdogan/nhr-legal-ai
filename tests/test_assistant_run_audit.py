"""The error map describes observations; it cannot certify legal correctness."""
import json

import pytest

from scripts.audit_assistant_runs import analyze_report, audit


def sample():
    return {'spent_usd': '0.003', 'output_token_cap_for_eval_only': 8192,
            'calls': [{'usage': {'cost': '0.001', 'completion_tokens': 8192}},
                      {'usage': {'cost': '0.002', 'completion_tokens': 100}}],
            'rows': [{'case': 'fixture', 'effort': 'low', 'seconds': 45, 'calls': 1,
                'answer': {'answer': 'Do not copy this body', 'citations': [{'title': 'Not proof of availability'}]},
                'timings': {'extra': {
                    'natural_stages_ms': {'planning': 44000, 'part_search': 400, 'write_and_check': 600},
                    'free_answer': {'coverage_preserved': True, 'partial_answer': True,
                        'source_admission': {'received': 5, 'over_budget': 1},
                        'sentence_outcomes': {'1': 'kod:numeric_polarity:number_or_unit', '2': 'denetçi_reddetti'},
                        'debug_why': {'1': 'Historic misaligned reason'},
                        'debug_removed': {'1': 'Do not copy this rejected body'}}}}}]}


def test_classifies_layers_without_calling_false_rejections_proven():
    result = analyze_report(sample(), 'fixture.json')
    row = result['rows'][0]
    assert set(row['signals']) == {'source_admission_loss', 'mechanical_rejection',
        'semantic_rejection_needs_review', 'coverage_flag_conflict',
        'possible_reason_id_misalignment', 'evaluation_output_cap_reached'}
    assert row['legal_correctness'] == 'not_determined'
    assert result['false_rejection_count'] == 'requires_source_and_claim_review'
    assert result['source_availability'].startswith('not_determined')
    assert 'Do not copy' not in json.dumps(result)


def test_does_not_double_count_rows_and_call_cost_or_ignore_interrupted_calls():
    result = analyze_report(sample(), 'fixture.json')
    assert result['spent_usd'] == '0.003'
    assert result['ledger_delta_usd'] == '0.000'
    assert result['calls_without_completed_row'] == 1


def test_stage_order_and_source_location_are_preserved():
    row = analyze_report(sample(), 'fixture.json')['rows'][0]
    assert row['location'] == 'fixture.json#/rows/0'
    assert row['slowest_stages_ms'][0] == {'stage': 'planning', 'ms': 44000}


def test_readiness_and_coverage_gaps_are_separate_from_semantic_rejections():
    report = sample()
    extra = report['rows'][0]['timings']['extra']
    extra['evidence_readiness'] = {'unready_parts': 1}
    extra['free_answer'] = {'coverage_preserved': False, 'uncovered_parts': ['one facet']}
    row = analyze_report(report, 'fixture.json')['rows'][0]
    assert 'retrieval_readiness_gap' in row['signals']
    assert 'reported_coverage_gap' in row['signals']
    assert 'semantic_rejection_needs_review' not in row['signals']


@pytest.mark.parametrize('count', [-1, 3, '1', True])
def test_invalid_call_attribution_fails_instead_of_assigning_wrong_latency(count):
    report = sample()
    report['rows'][0]['calls'] = count
    with pytest.raises(ValueError):
        analyze_report(report, 'fixture.json')


def test_audit_is_read_only_and_deduplicates_inputs(tmp_path):
    source = tmp_path / 'saved.json'
    raw = json.dumps(sample())
    source.write_text(raw, encoding='utf-8')
    result = audit([source])
    assert result['paid_calls_started'] == 0 and result['completed_rows'] == 1
    assert source.read_text(encoding='utf-8') == raw
    with pytest.raises(ValueError, match='Duplicate'):
        audit([source, source])
