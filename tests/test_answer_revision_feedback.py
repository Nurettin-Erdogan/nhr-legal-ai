import pytest

from api.ai import free_answer
from api.ai.synthesis import VerifiedAnswer


def test_targeted_patch_retains_verified_sentence_and_rechecks_combined_answer():
    import json
    from tests.test_free_answer import Provider, LAW, RULE_1, RULE_2, verdict

    incomplete = json.loads(verdict(1))
    incomplete["coverage_preserved"] = False
    provider = Provider(f"{RULE_1} @@ 1.1", json.dumps(incomplete),
                        f"{RULE_2} @@ 1.2", verdict(2))
    info = {}
    answer = free_answer.free_verified_answer(provider, question="Tazminat ve bildirim süresi?",
                                              contexts=[LAW], diagnostics=info)
    assert answer is not None and RULE_1 in answer.text and RULE_2 in answer.text
    patch_prompt = json.loads(provider.calls[2]["prompt"])
    assert patch_prompt["targeted_repair"]["retained_sentences_not_evidence"] == [[RULE_1]]
    combined_check = json.loads(provider.calls[3]["prompt"])
    assert [c["text"] for c in combined_check["claims"]] == [RULE_1, RULE_2]
    assert info["targeted_repair"] and info["coverage_preserved"]


def test_targeted_patch_cannot_bypass_numeric_guard():
    import json
    from tests.test_free_answer import Provider, LAW, RULE_1, verdict

    incomplete = json.loads(verdict(1))
    incomplete["coverage_preserved"] = False
    provider = Provider(f"{RULE_1} @@ 1.1", json.dumps(incomplete),
                        "Bildirim süresi 999 haftadır. @@ 1.2", json.dumps(incomplete))
    info = {}
    answer = free_answer.free_verified_answer(provider, question="Tazminat ve bildirim süresi?",
                                              contexts=[LAW], diagnostics=info)
    assert answer is not None and "999" not in answer.text
    assert info["partial_answer"]


@pytest.mark.parametrize('why,expected_searches', [
    ('kaynak_eksik: Diğer başvuru yolu için dayanak yok.', ['Başvuru yolları?']),
    ('ifade_duzelt: Dayanak var ama koşul açıklanmamış.', []),
])
def test_part_findings_reach_repair_and_only_explicit_evidence_gap_researches(monkeypatch, why, expected_searches):
    from tests.test_free_answer import LAW
    calls, searches = [], []

    def attempt(provider, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            kwargs['diagnostics'].update(coverage_preserved=False, kept=1, lead_removed=False,
                incomplete_parts=['Başvuru yolları?'],
                final_part_coverage=[dict(part_id=1, complete=False, why=why)])
        else:
            assert kwargs['revision_feedback']['part_findings'][0]['why'] == why
            kwargs['diagnostics'].update(coverage_preserved=True, kept=2, lead_removed=False)
        return VerifiedAnswer('checked answer', (), ())

    def retrieve(query):
        searches.append(query)
        return [LAW]

    monkeypatch.setattr(free_answer, '_free_verified_answer', attempt)
    answer = free_answer.free_verified_answer(object(), question='Başvuru yolları?', contexts=[LAW],
        retrieve=retrieve, parts=[('Başvuru yolları?', frozenset({LAW.chunk_id}))])
    assert answer is not None and len(calls) == 2
    assert searches == expected_searches


def test_rejection_categories_do_not_mistake_wording_for_missing_evidence():
    result = free_answer._rejection_categories({
        "sentence_outcomes": {"1": "kod:numeric_polarity:number_or_unit", "2": "denetçi_reddetti",
                              "3": "denetçi_reddetti", "4": "kaldı"},
        "debug_why": {"2": "ifade_duzelt: Koşulu koru.", "3": "kaynak_eksik: Ayrı yol yok."}})
    assert result == {"1": "numeric_or_polarity", "2": "wording_or_condition", "3": "missing_evidence"}


def test_repair_seed_is_invalidated_when_source_view_changes():
    import json
    from dataclasses import replace
    from tests.test_free_answer import Provider, LAW, RULE_1, RULE_2, verdict

    state = {}
    first = free_answer._free_verified_answer(Provider(f"{RULE_1} @@ 1.1", verdict(1)),
        question="Bildirim süresi?", contexts=[LAW], repair_state=state)
    assert first is not None and state["paragraphs"]
    changed = replace(LAW, content=RULE_2)
    provider = Provider(f"{RULE_2} @@ 1.1", verdict(1))
    info = {}
    second = free_answer._free_verified_answer(provider, question="Bildirim süresi?", contexts=[changed],
                                              repair_state=state, diagnostics=info)
    assert second is not None and RULE_1 not in second.text
    assert "targeted_repair" not in json.loads(provider.calls[0]["prompt"])
    assert not info.get("targeted_repair")


def test_checker_findings_keep_original_sentence_ids_after_numeric_rejection():
    import json
    from tests.test_free_answer import Provider, LAW, RULE_1, RULE_2, verdict
    check = json.loads(verdict(2, approved={2}))
    check['claims'][0]['why'] = 'ifade_duzelt: Gerekli koşulu koru.'
    draft = 'Bildirim süresi 999 haftadır. @@ 1.2\n' + RULE_1 + ' @@ 1.1\n' + RULE_2 + ' @@ 1.2'
    info = {}
    free_answer._free_verified_answer(Provider(draft, json.dumps(check)), question='Bildirim süresi?',
                                     contexts=[LAW], diagnostics=info)
    assert info['sentence_outcomes']['1'].startswith('kod:')
    assert '1' not in info['debug_why']
    assert info['debug_why']['2'].startswith('ifade_duzelt:')


def test_revision_fetches_missing_evidence_and_preserves_verified_feedback(monkeypatch):
    from tests.factories import legislation_context
    source = legislation_context()
    calls, searches = [], []

    def retrieve(query):
        searches.append(query)
        if query == "first part":
            raise RuntimeError("optional lane unavailable")
        return [source]

    def attempt(provider, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        if not first:
            assert source in kwargs["contexts"]
            assert kwargs["parts"][0][1] == frozenset()
            assert kwargs["parts"][1][1] == frozenset({source.chunk_id})
            assert kwargs["revision_feedback"]["previous_verified_answer"] == "checked subset"
        kwargs["diagnostics"].update(coverage_preserved=not first, kept=1, lead_removed=False)
        return VerifiedAnswer("checked subset" if first else "checked revision", (), ())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    answer = free_answer.free_verified_answer(object(), question="Several parts?", contexts=[], retrieve=retrieve,
        parts=[("first part", frozenset()), ("second part", frozenset())])
    assert answer.text == "checked revision" and searches == ["first part", "second part"]


@pytest.mark.parametrize("revised_kept,expected", [(7, "revised"), (2, "first")])
def test_substantial_loss_retries_with_findings_and_keeps_better_verified_answer(monkeypatch, revised_kept, expected):
    calls = []

    def attempt(provider, **kwargs):
        calls.append(kwargs.copy())
        info = kwargs["diagnostics"]
        if len(calls) == 1:
            info.update(draft_sentences=8, kept=5, removed=3, lead_removed=False,
                        debug_removed={"2": "A rejected claim"},
                        debug_why={"2": "A required condition was missing"})
            return VerifiedAnswer(text="first", contexts=(), unverified_markers=())
        assert kwargs["on_draft"] is None
        assert kwargs["revision_feedback"]["removed_sentences"] == ["A rejected claim"]
        assert "mechanical_findings" in kwargs["revision_feedback"]
        assert "repair_types" in kwargs["revision_feedback"]
        info.update(draft_sentences=8, kept=revised_kept, removed=8-revised_kept, lead_removed=False)
        return VerifiedAnswer(text="revised", contexts=(), unverified_markers=())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    info = {}
    answer = free_answer.free_verified_answer(object(), question="test", contexts=[], diagnostics=info)
    assert len(calls) == 2
    assert answer.text == expected
    assert info["attempts"] == 2


def test_revision_with_more_sentences_but_no_direct_answer_does_not_replace_good_opening(monkeypatch):
    calls = []

    def attempt(provider, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        kwargs["diagnostics"].update(
            draft_sentences=8 if first else 10, kept=5 if first else 8,
            removed=3 if first else 2, lead_removed=not first,
        )
        return VerifiedAnswer(text="direct" if first else "missing opening", contexts=(), unverified_markers=())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    info = {}
    answer = free_answer.free_verified_answer(object(), question="test", contexts=[], diagnostics=info)
    assert len(calls) == 2
    assert answer.text == "direct"
    assert info["lead_removed"] is False
    assert info["attempts"] == 2


def test_approved_but_incomplete_short_answer_gets_revised_without_more_attempts(monkeypatch):
    calls = []

    def attempt(provider, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        if not first:
            assert "coverage_issue" in kwargs["revision_feedback"]
        kwargs["diagnostics"].update(draft_sentences=3, kept=3 if first else 2,
                                     removed=0, lead_removed=False, coverage_preserved=not first)
        return VerifiedAnswer("incomplete" if first else "complete", (), ())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    info = {}
    answer = free_answer.free_verified_answer(object(), question="İki ayrı soru?", contexts=[], diagnostics=info)
    assert len(calls) == 2 and answer.text == "complete"
    assert info["coverage_preserved"] is True


def test_rejected_paraphrase_reuses_available_sources_instead_of_researching_each_sentence(monkeypatch):
    from tests.factories import legislation_context
    source = legislation_context()
    calls = []
    def forbidden(query):
        raise AssertionError('available evidence must be reused for a wording repair')
    def attempt(provider, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        kwargs['diagnostics'].update(coverage_preserved=not first, kept=1,
            lead_removed=False, debug_removed={'2': 'A badly worded claim'} if first else {})
        return VerifiedAnswer('checked subset' if first else 'checked revision', (source,), ())
    monkeypatch.setattr(free_answer, '_free_verified_answer', attempt)
    answer = free_answer.free_verified_answer(object(), question='Several parts?', contexts=[source],
        retrieve=forbidden, parts=[('A sourced part', frozenset({source.chunk_id}))], deferred_research=True)
    assert len(calls) == 2 and answer.text == 'checked revision'


def test_failed_local_first_coverage_opens_broad_discovery_before_the_checked_revision(monkeypatch):
    from tests.factories import legislation_context
    source = legislation_context()
    calls, searches = [], []
    def retrieve(query):
        searches.append(query)
        return [source]
    def attempt(provider, **kwargs):
        calls.append(True)
        kwargs['diagnostics'].update(coverage_preserved=len(calls) > 1, kept=1, lead_removed=False,
            debug_why={'1': 'kaynak_eksik: Gereken ayrı başvuru yolunun dayanağı mevcut değil.'} if len(calls) == 1 else {})
        return VerifiedAnswer('checked answer', (source,), ())
    monkeypatch.setattr(free_answer, '_free_verified_answer', attempt)
    answer = free_answer.free_verified_answer(object(), question='A sourced question?', contexts=[source],
        retrieve=retrieve, parts=[('A sourced part', frozenset({source.chunk_id}))], deferred_research=True)
    assert len(calls) == 2 and searches == ['A sourced part']
    assert answer.text == 'checked answer'


def test_verified_subset_keeps_partial_diagnostics_without_the_removed_generic_preface(monkeypatch):
    def attempt(provider, **kwargs):
        kwargs["diagnostics"].update(draft_sentences=2, kept=2, removed=0,
                                     lead_removed=False, coverage_preserved=False)
        return VerifiedAnswer("Only one part.", (), ())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    info = {}
    answer = free_answer.free_verified_answer(object(), question="Several parts?", contexts=[], diagnostics=info)
    assert answer.text == 'Only one part.'
    assert info['coverage_preserved'] is False
    assert info["partial_answer"] is True and info["attempts"] == 2


def test_a_global_incomplete_flag_next_to_a_fully_covered_part_table_does_not_cost_a_second_attempt(monkeypatch):
    from tests.factories import legislation_context
    source = legislation_context()
    calls = []

    def attempt(provider, **kwargs):
        calls.append(True)
        kwargs['diagnostics'].update(coverage_preserved=False, kept=13, lead_removed=False,
            final_part_coverage=[dict(part_id=1, complete=True, displayed_sentence_ids=[1, 2], why='')])
        return VerifiedAnswer('good answer', (source,), ())

    monkeypatch.setattr(free_answer, '_free_verified_answer', attempt)
    info = {}
    answer = free_answer.free_verified_answer(object(), question='A sourced question?', contexts=[source], diagnostics=info,
        parts=[('A sourced part', frozenset({source.chunk_id}))])
    assert answer.text == 'good answer' and len(calls) == 1 and info['partial_answer'] is True


def test_missing_sources_alone_do_not_trigger_a_rewrite_when_the_extra_search_finds_nothing_new(monkeypatch):
    from tests.factories import legislation_context
    source = legislation_context()
    calls, searches = [], []

    def retrieve(query):
        searches.append(query)
        return [source]  # nothing the answer did not already have

    def attempt(provider, **kwargs):
        calls.append(True)
        kwargs['diagnostics'].update(coverage_preserved=False, kept=5, lead_removed=False,
            final_part_coverage=[dict(part_id=1, complete=False, displayed_sentence_ids=[1], why='kaynak_eksik: dayanak yok')])
        return VerifiedAnswer('answer', (source,), ())

    monkeypatch.setattr(free_answer, '_free_verified_answer', attempt)
    answer = free_answer.free_verified_answer(object(), question='A question?', contexts=[source], retrieve=retrieve,
        parts=[('A sourced part', frozenset({source.chunk_id}))])
    assert answer.text == 'answer' and len(calls) == 1 and searches == ['A sourced part']
