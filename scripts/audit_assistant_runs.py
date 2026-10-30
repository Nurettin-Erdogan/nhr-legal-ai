"""Read saved evaluation reports only: no app imports, models, DB or network.

Signals identify where to investigate, not whether a legal claim is correct.
No question, answer, prompt, header or source body is copied into the summary.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path


def analyze_report(report: dict, name: str) -> dict:
    rows, calls = report.get('rows', []), report.get('calls', [])
    if not isinstance(rows, list) or not isinstance(calls, list):
        raise ValueError('Expected rows and calls arrays')
    output, cursor = [], 0
    for index, row in enumerate(rows):
        info = row.get('timings', {}).get('extra', {})
        check = info.get('free_answer', {})
        outcomes = check.get('sentence_outcomes', {})
        mechanical = {k: v for k, v in outcomes.items() if str(v).startswith('kod:')}
        semantic = [k for k, v in outcomes.items() if v == 'denetçi_reddetti']
        admission = check.get('source_admission', {})
        signals = []
        if info.get('evidence_readiness', {}).get('unready_parts', 0):
            signals.append('retrieval_readiness_gap')
        if admission.get('unusable', 0) or admission.get('over_budget', 0):
            signals.append('source_admission_loss')
        if mechanical:
            signals.append('mechanical_rejection')
        if semantic:
            signals.append('semantic_rejection_needs_review')
        if check.get('coverage_preserved') is False or check.get('uncovered_parts'):
            signals.append('reported_coverage_gap')
        if check.get('coverage_preserved') is True and (
                check.get('partial_answer') or check.get('uncovered_parts')):
            signals.append('coverage_flag_conflict')
        # Historic reports may contain candidate-index reasons attached to
        # original draft-index outcomes. Do not infer entailment from them.
        if set(mechanical) & set(check.get('debug_why', {})):
            signals.append('possible_reason_id_misalignment')
        count = row.get('calls', 0)
        if type(count) is not int or count < 0 or cursor + count > len(calls):
            raise ValueError('Invalid completed-row call allocation')
        owned = calls[cursor:cursor + count]
        cap = report.get('output_token_cap_for_eval_only')
        if cap and any(c.get('usage', {}).get('completion_tokens', 0) >= cap for c in owned):
            signals.append('evaluation_output_cap_reached')
        cursor += count
        stages = info.get('natural_stages_ms', {})
        ordered = sorted(((k, v) for k, v in stages.items()
                          if type(v) in (int, float) and v >= 0), key=lambda pair: -pair[1])
        output.append({
            'location': f'{name}#/rows/{index}', 'case': row.get('case'), 'effort': row.get('effort'),
            'seconds': row.get('seconds'), 'signals': signals,
            'mechanical_counts': {reason: sum(v == reason for v in mechanical.values())
                                  for reason in sorted(set(mechanical.values()))},
            'semantic_rejections': len(semantic),
            'coverage_preserved': check.get('coverage_preserved'),
            'partial_answer': bool(check.get('partial_answer')),
            'uncovered_part_count': len(check.get('uncovered_parts', [])),
            'source_admission': admission,
            'slowest_stages_ms': [{'stage': k, 'ms': v} for k, v in ordered[:3]],
            'legal_correctness': 'not_determined',
        })
    spent = Decimal(str(report.get('spent_usd', 0)))
    known = sum((Decimal(str(c.get('usage', {}).get('cost', 0))) for c in calls), Decimal(0))
    if not spent.is_finite() or not known.is_finite() or spent < 0 or known < 0:
        raise ValueError('Invalid ledger')
    return {'report': name, 'rows': output, 'charged_calls': len(calls),
            'calls_without_completed_row': len(calls) - cursor,
            'spent_usd': str(spent), 'reported_call_cost_usd': str(known),
            'ledger_delta_usd': str(spent - known), 'stopped': report.get('stopped'),
            'source_availability': 'not_determined_from_titles_or_citation_counts',
            'false_rejection_count': 'requires_source_and_claim_review'}


def audit(paths: list[Path]) -> dict:
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError('Duplicate report path')
    reports = [analyze_report(json.loads(p.read_text(encoding='utf-8')), p.name) for p in paths]
    return {'paid_calls_started': 0, 'mode': 'saved_report_analysis', 'reports': reports,
            'completed_rows': sum(len(r['rows']) for r in reports),
            'historic_spent_usd': str(sum((Decimal(r['spent_usd']) for r in reports), Decimal(0)))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.reports)
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(serialized + '\n')
    print(json.dumps({'paid_calls_started': 0, 'reports': len(result['reports']),
                      'completed_rows': result['completed_rows'],
                      'historic_spent_usd': result['historic_spent_usd']}))


if __name__ == '__main__':
    main()
