"""Minimal synthetic reproductions of observed binding failures, not legal advice.

These are not a frozen copy of the full historical model request. A mechanical
pass below deliberately requires a separate semantic review.
"""
from dataclasses import replace

from scripts.diagnose_claim_evidence import inspect_binding
from tests.factories import legislation_context


def source():
    return legislation_context(content=(
        'Yıllık ücretli izin süresi ondört günden az olamaz. '
        'Yer altı işlerinde çalışan işçilerin izin süreleri dörder gün artırılır. '
        'İş sözleşmesiyle izin süreleri artırılabilir.'))


def test_missing_minimum_binding_is_not_a_reason_to_remove_the_minimum_guard():
    context = source()
    claim = 'Bu asgari izin süreleri dört gün artırılır.'
    wrong = inspect_binding(claim, [{'source': 1, 'unit': 2}], [context])
    repaired = inspect_binding(claim, [{'source': 1, 'unit': 1}, {'source': 1, 'unit': 2}], [context])
    assert wrong['status'] == 'mechanical_rejection'
    assert 'minimum_added' in wrong['checks']
    assert repaired['status'] == 'requires_semantic_review'
    assert repaired['semantic_support'] == 'not_determined'


def test_added_lower_bound_without_a_source_still_fails():
    context = legislation_context(content='İzin süresi ondört gündür.')
    result = inspect_binding('İzin süresi en az 14 gündür.', [{'source': 1, 'unit': 1}], [context])
    assert result['status'] == 'mechanical_rejection'
    assert 'minimum_added' in result['checks']


def test_wrong_duration_is_not_repaired_by_correct_qualifier_binding():
    result = inspect_binding('Asgari süreler beş gün artırılır.',
        [{'source': 1, 'unit': 1}, {'source': 1, 'unit': 2}], [source()])
    assert result['status'] == 'mechanical_rejection'
    assert 'number_or_unit' in result['checks']


def test_forged_quote_never_becomes_a_resolved_source_unit():
    result = inspect_binding('İzin süresi en az 90 gündür.',
        [{'source': 1, 'quote': 'İzin süresi en az 90 gündür.'}], [source()])
    assert result['status'] == 'mechanical_rejection' and result['reason'] == 'evidence'


def test_fixture_pins_exact_text_and_source_identity_without_mutating_it():
    context = replace(source(), source_version='fixture-v1', revision=3)
    before = (context.content, context.source_version, context.revision, context.chunk_id)
    result = inspect_binding('İzin süreleri dört gün artırılır.', [{'source': 1, 'unit': 2}], [context])
    unit = result['bound_units'][0]
    assert unit['source_version'] == 'fixture-v1' and unit['revision'] == 3
    assert unit['source_id'] == str(context.source_id)
    assert len(unit['content_sha256']) == 64
    assert (context.content, context.source_version, context.revision, context.chunk_id) == before


def test_invalid_unit_index_cannot_be_mistaken_for_supported_text():
    result = inspect_binding('İzin süreleri dört gün artırılır.', [{'source': 1, 'unit': 99}], [source()])
    assert result['status'] == 'mechanical_rejection'
    assert result['bound_units'] == []
