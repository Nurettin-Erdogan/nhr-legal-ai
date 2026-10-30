import importlib.util
import json
from pathlib import Path
import pytest
from api.ai.official_sources import SOURCES, source_for_url
from ingestion.official_catalog import COLLECTIONS, collection_report, coverage_state


def test_all_institutions_have_collection_scope_without_claiming_importers():
    report = collection_report()
    assert {c['source'] for c in report} == {s.key for s in SOURCES}
    assert len({c['source'] for c in report}) == 21
    assert len(report) == 25  # The existing AYM adapter handles five distinct decision types.
    assert all(source_for_url(c['official_entry']) for c in report)
    assert all(c['coverage'] == 'coverage_unknown' and c['official_inventory_total'] is None for c in report)
    assert all(c['module'] is None for c in report if c['capability'] == 'adapter_missing')


def test_existing_modules_are_real_not_guessed_worker_names():
    root = Path(__file__).resolve().parents[1]
    for collection in COLLECTIONS:
        if collection.module:
            assert (root / (collection.module.replace('.', '/') + '.py')).is_file()


def test_big_local_count_does_not_prove_completeness():
    assert coverage_state(imported_ids=11_000_000, verified_ids=11_000_000) == 'coverage_unknown'
    assert coverage_state(enumerated=True, official_ids=12, imported_ids=12,
                          verified_ids=11, unresolved=1) == 'incomplete'
    assert coverage_state(enumerated=True, official_ids=12, imported_ids=12,
                          verified_ids=12, unresolved=0) == 'snapshot_complete'
    assert coverage_state(enumerated=True, official_ids=12, imported_ids=14,
                          verified_ids=12, unresolved=0) == 'inventory_inconsistent'


@pytest.mark.parametrize('value', [-1, True, '12'])
def test_invalid_counts_fail_closed(value):
    with pytest.raises(ValueError):
        coverage_state(official_ids=value)


def inventory_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/official_data_inventory.py'
    spec = importlib.util.spec_from_file_location('official_inventory_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partial_articles_and_failed_laws_stay_open(tmp_path):
    module = inventory_module()
    journal = tmp_path / 'journal.jsonl'
    journal.write_text('\n'.join(json.dumps(row) for row in [
        dict(law='1', status='partial', preview={'skipped': [{'article': '80', 'reason': 'ambiguous'}]}),
        dict(law='2', status='preview_failed_no_change', reason='portal_unavailable'),
    ]), encoding='utf-8')
    report = module.refresh_progress(journal, tmp_path / 'absent.json')
    assert len(report['law_refresh']['unresolved_items']) == 2
    assert report['law_refresh']['complete'] is False
    assert report['text_hash_scan']['scanned'] is None


def test_corpus_counters_are_not_relabelled_as_verified_coverage():
    report = inventory_module().build_report([{'key': 'src|court_decision|Yargıtay', 'n': 11_000_000}])
    assert report['stored_counter_totals'] == {'court_decision': 11_000_000}
    assert report['complete'] is False
    assert all(c['official_inventory_total'] is None for c in report['collections'])
