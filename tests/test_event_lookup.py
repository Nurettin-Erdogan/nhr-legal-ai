from dataclasses import replace
from datetime import date

from api.ai.dialogue import outcome_search_query
from api.ai.event_lookup import lookup_event_basis, load_current_event_reference
from tests.factories import legislation_context


FIRST = "ben 10 sene çalıştım ne kadar çıkış parası alırım"
DETAILS = "50000 brüt ücret 12 kasım 2005 13 mart 2016"
LAST = "küçülmeye gittiler çıkardılar"


def run(loader, **kwargs):
    return lookup_event_basis(LAST,outcome_search_query(LAST,prior_questions=[FIRST,DETAILS]),
                             prior_questions=[FIRST,DETAILS],loader=loader,**kwargs)


def test_exact_reference_reads_preserve_target_date_and_do_not_invent_historical_data():
    seen = []
    def load(ref,target):
        seen.append((ref,target))
        return []
    result = run(load)
    assert not result.complete and result.contexts == ()
    assert set(ref for ref,_ in seen) == {("1475","14"),("4857","17")}
    assert all(target == date(2016,3,13) for _,target in seen)


def test_same_event_in_one_message_has_the_same_temporal_guard_as_three_turns():
    question = f"{FIRST}, {DETAILS}, {LAST}"
    targets = []
    result = lookup_event_basis(question, outcome_search_query(question),
        loader=lambda ref, target: targets.append(target) or [])
    assert result is not None and not result.complete
    assert set(targets) == {date(2016, 3, 13)}


def test_current_version_without_valid_interval_never_satisfies_historical_basis():
    result = run(lambda ref,target:[replace(legislation_context(),law_no=ref[0],article_no=ref[1],
                       version_date=date(2024,7,10),effective_from=None,effective_to=None)])
    assert not result.complete


def test_only_all_required_temporally_verified_references_complete_the_basis():
    def load(ref,target):
        return [replace(legislation_context(),law_no=ref[0],article_no=ref[1],
                        effective_from=date(2000,1,1),effective_to=date(2018,1,1))]
    assert run(load).complete
    result = run(lambda ref,target:load(ref,target) if ref[0]=="1475" else [])
    assert not result.complete


def test_explicit_as_of_is_not_silently_replaced_by_the_employment_date():
    targets = []
    run(lambda ref,target:targets.append(target) or [],as_of=date(2015,1,1))
    assert set(targets) == {date(2015,1,1)}


def test_general_or_incomplete_question_does_not_trigger_event_basis_lookup():
    def fail(*args):
        raise AssertionError("No temporal lookup for an incomplete/general question")
    assert lookup_event_basis("İşçinin hakları nelerdir?","işçi",loader=fail) is None


def test_current_reference_cannot_turn_missing_historical_proof_into_verified_coverage():
    lookup = run(lambda *args: [])
    calls = []
    def load(ref, target):
        calls.append(target)
        return [replace(legislation_context(), law_no=ref[0], article_no=ref[1],
                        version_date=date(2026,1,1), effective_from=None, effective_to=None)]
    references = load_current_event_reference(lookup, loader=load)
    assert references and calls == [None] * len(lookup.references)
    assert not lookup.complete and lookup.contexts == ()
    assert not lookup.event.applicability_verified and lookup.event.historical_basis_missing


def test_current_reference_excludes_unverified_wrong_article_and_clipped_results():
    lookup = run(lambda *args: [])
    source = replace(legislation_context(), law_no="1475", article_no="14")
    assert load_current_event_reference(lookup, loader=lambda *args:[replace(source,verification="third_party")]) == []
    assert load_current_event_reference(lookup, loader=lambda *args:[source]*16) == []
    assert load_current_event_reference(lookup, loader=lambda *args:[replace(source,article_no="99")]) == []
