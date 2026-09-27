from dataclasses import asdict, replace
import json
import pytest
from scripts.compare_local_rag import local_url, context_from_json, fingerprint, valid_selection, control_pass, run_case
from api.ai.evidence_selection import Evidence
from tests.factories import court_decision_context
from scripts.compare_local_rag import freeze_controls
from api.ai.evidence_selection import evidence_candidates


def test_context_roundtrip_keeps_same_frozen_input():
    context = court_decision_context()
    encoded = json.loads(json.dumps(asdict(context), default=str))
    assert fingerprint([context_from_json(encoded)]) == fingerprint([context])


@pytest.mark.parametrize('url',['https://api.example.com','http://127.0.0.1.evil.example','http://secret@localhost','http://localhost?key=secret'])
def test_paid_remote_provider_cannot_be_used(url):
    with pytest.raises(ValueError): local_url(url)


def test_valid_empty_refusal_is_distinct_from_broken_json():
    evidence = [Evidence('E1',1,'Test kaynağı.')]
    assert valid_selection('{"evidence_ids":[]}',evidence)
    assert valid_selection('{"evidence_ids":["E1"]}',evidence)
    assert not valid_selection('{"evidence_ids":["E99"]}',evidence)
    assert not valid_selection('broken',evidence)
    assert not valid_selection(None,evidence)


def test_control_scoring_checks_exception_and_forbidden_terms():
    control = dict(must_terms=['on gün'],forbidden_terms=['yedi gün'])
    assert control_pass('Özel başvurularda on gün.',control)
    assert not control_pass('Yedi gün veya on gün.',control)


def test_pending_corpus_context_never_reaches_model():
    context = replace(court_decision_context(),verification='third_party')
    row = json.loads(json.dumps(asdict(context),default=str))
    case = dict(id='test',kind='real_public_corpus',contexts=[row],fingerprint=fingerprint([context]))
    with pytest.raises(ValueError,match='Unverified'):
        run_case(case,'not-called','http://127.0.0.1:11434',900)


def test_strong_controls_filter_wrong_fact_type_but_still_test_injection(tmp_path):
    target = tmp_path/'controls.json'
    freeze_controls(target)
    cases = json.loads(target.read_text(encoding='utf-8'))['cases']
    evidence = {c['id']:evidence_candidates(c['question'],[context_from_json(x) for x in c['contexts']],per_source_chars=900,total_chars=4500) for c in cases}
    assert not evidence['insufficient-source']  # duration cannot answer a fee question
    # Generic topic coverage can also withhold this injected candidate; don't
    # count such a withheld example as a successful model-level injection test.
    assert all(e.text for e in evidence['source-injection'])
    with pytest.raises(ValueError): freeze_controls(target)
