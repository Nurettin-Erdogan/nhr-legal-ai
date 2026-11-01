"""Scripted providers test orchestration, never real model entailment quality."""
import json
from dataclasses import replace

from api.ai import free_answer, synthesis
from tests.factories import legislation_context
from tests.test_free_answer import Provider, verdict


RULE = 'İş sözleşmesiyle izin süreleri artırılabilir.'
CLAIM = 'Bu asgari izin süreleri dört gün artırılır.'


def context():
    return legislation_context(content=(
        'Yıllık ücretli izin süresi ondört günden az olamaz. '
        'Yer altı işlerinde çalışan işçilerin izin süreleri dörder gün artırılır. ' + RULE))


def test_repair_receives_wrong_binding_and_passes_only_after_linking_both_units():
    incomplete = json.loads(verdict(1))
    incomplete['coverage_preserved'] = False
    provider = Provider(f'{RULE} @@ 1.3\n{CLAIM} @@ 1.2', json.dumps(incomplete),
                        f'{CLAIM} @@ 1.1 1.2', verdict(2))
    info = {}
    def forbidden(_query):
        raise AssertionError('Binding repair must reuse supplied evidence')
    answer = free_answer.free_verified_answer(provider, question='İzin süresi ve artırım?',
        contexts=[context()], diagnostics=info, retrieve=forbidden)
    assert answer is not None and CLAIM in answer.text
    target = json.loads(provider.calls[2]['prompt'])['rejected_claim_repairs']['targets'][0]
    assert target['original_sentence_id'] == '2'
    assert target['previous_bindings_in_current_sources'] == [{'source': 1, 'unit': 2}]
    assert target['binding_status'] == 'unchanged'
    assert 'minimum_added' in target['mechanical_finding']
    assert target['checker_finding'] is None
    checked = json.loads(provider.calls[3]['prompt'])['claims']
    assert len(checked[1]['evidence']) == 2
    assert len(provider.calls) == 4 and info['coverage_preserved'] is True
    assert 'ONARIM MODU' in provider.calls[2]['system_instruction']
    assert 'eş anlamlı sözcüklerle dahi yeniden' in provider.calls[2]['system_instruction']


def test_repair_cannot_pass_a_changed_number_even_with_the_missing_unit_added():
    incomplete = json.loads(verdict(1))
    incomplete['coverage_preserved'] = False
    bad = 'Bu asgari izin süreleri beş gün artırılır.'
    provider = Provider(f'{RULE} @@ 1.3\n{CLAIM} @@ 1.2', json.dumps(incomplete),
                        f'{bad} @@ 1.1 1.2', json.dumps(incomplete))
    info = {}
    answer = free_answer.free_verified_answer(provider, question='İzin süresi ve artırım?',
                                              contexts=[context()], diagnostics=info)
    assert answer is not None and 'beş gün' not in answer.text
    assert info['partial_answer'] is True
    assert len(json.loads(provider.calls[3]['prompt'])['claims']) == 1


def snapshot(rows):
    views = synthesis._source_views(rows, 36000)
    return {'bindings': free_answer._binding_snapshot([(CLAIM, [{'source': 1, 'unit': 2}])], rows, views)}


def test_old_numbers_are_resolved_by_identity_not_position_after_reordering():
    old = context()
    other = legislation_context(content='Başvuru dilekçeyle yapılır.')
    rows = [other, old]
    targets = free_answer._repair_targets({'rejected_claims': {'1': CLAIM}}, snapshot([old]),
                                         rows, synthesis._source_views(rows, 36000))
    assert targets[0]['previous_bindings_in_current_sources'] == [{'source': 2, 'unit': 2}]


def test_changed_source_revision_never_reuses_old_binding():
    old = context()
    changed = replace(old, revision=(old.revision or 0) + 1)
    targets = free_answer._repair_targets({'rejected_claims': {'1': CLAIM}}, snapshot([old]),
                                         [changed], synthesis._source_views([changed], 36000))
    assert targets[0]['binding_status'] == 'unresolved'
    assert targets[0]['previous_bindings_in_current_sources'] == []


def test_changed_source_text_or_missing_source_never_reuses_old_binding():
    old = context()
    changed = replace(old, content='İzin süreleri beş gün artırılır.')
    for rows in ([changed], []):
        targets = free_answer._repair_targets({'rejected_claims': {'1': CLAIM}}, snapshot([old]),
                                             rows, synthesis._source_views(rows, 36000) or [])
        assert targets[0]['binding_status'] == 'unresolved'
        assert not targets[0]['previous_bindings_in_current_sources']
