"""Kaynaklardan akıcı cevap (api/ai/free_answer.py): her cümle bir kaynak cümlesine bağlı yazılır, kaynaktan kopan cümle sessizce çıkar."""

from __future__ import annotations

import json

from api.ai import free_answer
from api.ai.free_answer import free_verified_answer
from tests.factories import court_decision_context, legislation_context

RULE_1 = "İşveren bildirim süresine uymazsa bu süreye ait ücret tutarında tazminat ödemek zorundadır."
RULE_2 = "Bildirim süresi işi altı aydan az sürmüş işçi için iki haftadır."
LAW = legislation_context(content=f"{RULE_1} {RULE_2}")
DECISION = court_decision_context(
    chunk_id="00000000-0000-0000-0000-000000000031", source_id="00000000-0000-0000-0000-000000000032",
    content="Davacı işçi bildirim süresine uyulmadan işten çıkarılmıştır. Mahkeme ihbar tazminatına hükmetmiştir.")

DRAFT = (
    "İşveren bildirim süresine uymadan sözleşmeyi feshederse bu süreye ait ücret tutarında tazminat ödemek zorundadır. @@ 1.1\n"
    "İşi altı aydan kısa süren işçi için bu süre iki haftadır. @@ 1.2\n\n"
    "Yargıtay uygulamasında mahkeme bu durumda ihbar tazminatına hükmetmiştir. @@ 2.2"
)


class Provider:
    name = "test"
    model = "fixture"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class RoutedProvider:
    """Answers by kind of call, so parts written in parallel (any order) get the draft and the checker gets a matching verdict."""
    name = "test"
    model = "fixture"

    def __init__(self, draft, part_rows):
        self.draft, self.part_rows, self.calls = draft, part_rows, []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_instruction"] == free_answer.WRITE_INSTRUCTION:
            return self.draft
        return with_parts(verdict(len(json.loads(kwargs["prompt"])["claims"])), self.part_rows)

    def checker_calls(self):
        return [c for c in self.calls if c["system_instruction"] not in (free_answer.WRITE_INSTRUCTION,
                                                                          free_answer._CROSS_PART_DUPLICATE_INSTRUCTION)]


def verdict(count, approved=None):
    approved = set(range(1, count + 1)) if approved is None else approved
    return json.dumps({"claims": [{"id": i, "supported": i in approved, "relevant": True, "scope_preserved": i in approved}
                                  for i in range(1, count + 1)],
                       "coverage_preserved": True, "source_only": True, "clarification_safe": True})


def with_parts(raw, rows):
    value = json.loads(raw)
    value['part_coverage'] = [{'part_id': i, 'claim_ids': ids, 'complete': bool(ids), 'why': ''}
                              for i, ids in enumerate(rows, 1)]
    return json.dumps(value)


def run(draft, check, *, contexts=(LAW, DECISION), drafts=None):
    provider = Provider(*[r for r in (draft, check) if r is not None])
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=list(contexts),
                                  diagnostics=info, on_draft=None if drafts is None else drafts.append)
    return answer, info, provider


def test_the_answer_is_flowing_paragraphs_with_the_real_sources_of_each_paragraph():
    answer, info, provider = run(DRAFT, verdict(3))
    assert answer is not None and info["status"] == "accepted" and info["kept"] == 3 and info["removed"] == 0
    first, second = answer.text.split("\n\n")
    assert first.count("bildirim süresine") >= 1 and second.startswith("Yargıtay")
    assert "[K" not in answer.text and "doğrulanamadı" not in answer.text and "Not:" not in answer.text  # no markers, labels
    assert [c.chunk_id for c in answer.contexts] == [LAW.chunk_id, DECISION.chunk_id]
    sources = json.loads(provider.calls[0]["prompt"])["sources"]
    assert [s["source"] for s in sources] == [1, 2] and sources[0]["evidence_units"][0]["unit"] == 1


def test_long_source_linked_answer_is_not_rejected_by_sentence_or_paragraph_count():
    draft = '\n\n'.join('\n'.join(f'{RULE_1} @@ 1.1' for _ in range(5)) for _ in range(8))
    parsed = free_answer._parse(draft)
    assert len(parsed) == 8
    assert sum(map(len, parsed)) == 40
    assert all(evidence == [{'source': 1, 'unit': 1}] for paragraph in parsed for _, evidence in paragraph)


def test_writing_policy_follows_user_length_and_explains_instead_of_pasting():
    policy = free_answer.WRITE_INSTRUCTION
    assert 'En çok 5 paragraf' not in policy and 'en çok 16 cümle' not in policy
    assert 'kısa/özet isterse kısa' in policy
    assert 'Sabit paragraf veya cümle sayısı sınırı yoktur' in policy
    assert 'Kaynak metinlerini arka arkaya yapıştırma' in policy


def test_natural_application_policy_is_not_restricted_to_first_sentence():
    policy = free_answer.LEAD_CHECK_INSTRUCTION
    assert 'YALNIZ id=1' not in policy
    assert 'Bu izin cümle numarasına bağlı değildir' in policy
    assert 'Bütün öncüller evidence veya user_question içinde' in policy
    assert 'soruda verilmeyen bir şartın sağlandığını varsaymak' in policy
    assert 'supported=false ve scope_preserved=false' in policy


def test_checker_gets_entire_cited_source_but_not_unrelated_search_hits():
    unrelated = legislation_context(chunk_id='00000000-0000-0000-0000-000000000091',
        source_id='00000000-0000-0000-0000-000000000092', content='Dernek yönetim kurulu üyelerini genel kurul seçer.')
    answer, info, provider = run(f'{RULE_1} @@ 1.1', verdict(1), contexts=(LAW, unrelated))
    assert answer is not None
    payload = json.loads(provider.calls[1]['prompt'])
    assert [s['source'] for s in payload['sources']] == [1]
    assert RULE_2 in payload['sources'][0]['text']  # no hidden source condition is clipped
    assert info['checker_source_count'] == 1


def test_checker_coverage_policy_evaluates_only_the_approved_subset():
    assert 'yalnız supported=true, relevant=true ve scope_preserved=true' in free_answer.LEAD_CHECK_INSTRUCTION
    assert 'discarded_before_review' in free_answer.LEAD_CHECK_INSTRUCTION


def test_checker_receives_paragraph_context_without_turning_it_into_evidence():
    answer, _, provider = run(DRAFT, verdict(3))
    assert answer is not None
    claims = json.loads(provider.calls[1]['prompt'])['claims']
    assert [c['paragraph'] for c in claims] == [1, 1, 2]
    assert all(c['evidence'] for c in claims)
    assert 'yalnız sunum bağlamıdır, hukuki kanıt değildir' in free_answer.LEAD_CHECK_INSTRUCTION


def test_unrepresented_part_sources_still_reach_the_coverage_checker():
    other = legislation_context(chunk_id='00000000-0000-0000-0000-000000000093',
        source_id='00000000-0000-0000-0000-000000000094', content='Başvuru yazılı dilekçe ile yapılır.')
    provider = RoutedProvider(f'{RULE_1} @@ 1.1', [[1, 2], []])
    free_answer._free_verified_answer(provider, question='İki ayrı başlık?', contexts=[LAW, other],
        parts=[('İlk başlık', frozenset({LAW.chunk_id})), ('Diğer başlık', frozenset({other.chunk_id}))])
    payload = json.loads(provider.checker_calls()[0]['prompt'])
    assert [s['source'] for s in payload['sources']] == [1, 2]


def test_a_sentence_the_independent_checker_rejects_is_removed_silently():
    answer, info, _ = run(DRAFT, verdict(3, approved={1, 3}))
    assert answer is not None and info["kept"] == 2 and info["removed"] == 1
    assert "iki haftadır" not in answer.text and "doğrulanamadı" not in answer.text
    assert "[K" not in answer.text and answer.text.split("\n\n")[0].startswith("İşveren")


def test_a_sentence_that_cites_a_source_sentence_that_does_not_exist_is_dropped_by_the_code():
    draft = DRAFT.replace("@@ 1.2", "@@ 1.9")
    answer, info, provider = run(draft, verdict(2))
    assert answer is not None and info["removed"] == 1 and "iki haftadır" not in answer.text
    assert len(json.loads(provider.calls[1]["prompt"])["claims"]) == 2  # the checker never sees the invalid one


def test_a_number_the_cited_sentence_does_not_contain_never_survives_even_if_the_checker_approves():
    draft = DRAFT.replace("bu süre iki haftadır", "bu süre üç haftadır")
    answer, info, _ = run(draft, verdict(2))
    assert answer is not None and "üç haftadır" not in answer.text and info["removed"] == 1


def test_nothing_proven_is_retried_once_and_then_means_no_answer():
    provider = Provider(*[DRAFT, verdict(3, approved=set())] * 3)
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is None and info["reason"] == "checker" and info["attempts"] == 2 and len(provider.calls) == 4


def test_a_single_proven_sentence_is_still_an_answer():
    answer, info, _ = run(DRAFT, verdict(3, approved={1}))
    assert answer is not None and info["kept"] == 1 and "[K" not in answer.text


def test_a_bad_first_attempt_is_repaired_by_the_second_and_the_preview_is_not_repeated():
    drafts: list[str] = []
    bad = DRAFT.replace("@@ 1.1", "@@ 1.8").replace("@@ 1.2", "@@ 1.8").replace("@@ 2.2", "@@ 2.8")
    provider = Provider(bad, DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info, on_draft=drafts.append)
    assert answer is not None and info["attempts"] == 2 and info["kept"] == 3 and len(drafts) == 1


def test_the_draft_is_previewed_once_before_the_proof():
    drafts: list[str] = []
    answer, _info, provider = run(DRAFT, verdict(3), drafts=drafts)
    assert answer is not None and len(drafts) == 1 and len(provider.calls) == 2
    assert "[K" not in drafts[0] and "@@" not in drafts[0] and drafts[0].count("\n\n") == 1


def test_a_users_own_document_is_never_sent_through_this_route():
    from tests.factories import document_context

    answer, info, provider = run(DRAFT, verdict(3), contexts=(document_context(),))
    assert answer is None and info["reason"] == "no_sources" and provider.calls == []


def test_a_sentence_that_refers_back_to_a_removed_sentence_goes_with_it():
    draft = (
        "İşveren bildirim süresine uymazsa bu süreye ait ücret tutarında tazminat ödemek zorundadır. @@ 1.1\n\n"
        "Tazminata yalnız belirli sebeplerle hak kazanılır diye eski bir iddia yazılmıştır burada. @@ 1.1\n"
        "Ancak bu tazminat bildirim süresine ait ücret tutarında ödenir. @@ 1.1\n"
        "İşi altı aydan az sürmüş işçi için bildirim süresi iki haftadır. @@ 1.2"
    )
    provider = Provider(draft, verdict(4, approved={1, 3, 4}))
    info = {}
    # Exercise one pass: the wrapper now correctly requests a repair after
    # structural filtering invalidates the checker's earlier coverage verdict.
    answer = free_answer._free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?",
                                               contexts=[LAW, DECISION], diagnostics=info)
    assert answer is not None and "Ancak bu tazminat" not in answer.text and "iki haftadır" in answer.text
    assert info["dangling_removed"] == 1 and info["lead_removed"] is False
    assert info["coverage_preserved"] is False and info["partial_answer"] is True


def test_checked_transition_across_paragraphs_keeps_its_shown_predecessor():
    draft = (RULE_1 + ' @@ 1.1\n\n'
             'Ayrıca, işi altı aydan az sürmüş işçi için bildirim süresi iki haftadır. @@ 1.2')
    answer, info, _ = run(draft, verdict(2), contexts=(LAW,))
    assert answer is not None
    assert '\n\nAyrıca,' in answer.text
    assert not info.get('dangling_removed')


def test_an_answer_whose_direct_first_sentence_was_not_proven_is_written_again():
    provider = Provider(DRAFT, verdict(3, approved={2, 3}), DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 2 and info["kept"] == 3 and not info["lead_removed"]


def test_a_lost_lead_uses_one_checked_answer_revision_not_two_extra_lead_calls():
    provider = Provider(DRAFT, verdict(3, approved={2, 3}), DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 2 and not info["lead_removed"]
    assert answer.text.startswith("İşveren bildirim süresine")
    assert not any(call['system_instruction'] == free_answer.LEAD_INSTRUCTION for call in provider.calls)
    assert "@@" not in answer.text and len(provider.calls) == 4


def test_a_rebuilt_lead_the_checker_rejects_is_not_used():
    provider = Provider(DRAFT, verdict(3, approved={2, 3}), DRAFT, verdict(3, approved={2, 3}))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 2 and info["kept"] == 2
    assert 'İşveren bildirim süresine uymadan' not in answer.text


def test_a_proven_independent_sentence_survives_even_when_the_lead_is_rejected():
    provider = Provider(*[DRAFT, verdict(3, approved={3})] * 3)
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and answer.grounded and info["attempts"] == 2
    assert info["partial_answer"] is True
    assert "Sorunuzun tamamını" not in answer.text  # a missing lead alone is not a coverage verdict
    assert "Yargıtay uygulamasında" in answer.text
    assert "İşveren bildirim" not in answer.text


def test_simple_single_topic_does_not_call_a_planner():
    class NoCalls:
        def generate(self, **kwargs):
            raise AssertionError('simple topic must not spend a planning call')
    assert free_answer.plan_question(NoCalls(), 'İşe iade şartları nelerdir?')[0][0] == 'İşe iade şartları nelerdir?'
    assert free_answer.simple_search_plan('Nafaka ve mal paylaşımı hangi sürede istenir?') is None
    assert free_answer.simple_search_plan('İki Yargıtay kararıyla işe iadeyi açıkla') is None


def test_several_sentences_on_one_line_and_unit_ranges_are_read_correctly():
    parsed = free_answer._parse(
        "Birinci cümle burada yazıldı. @@ 1.1 İkinci cümle de aynı satırda yazıldı. @@ 1.3 2.1 "
        "Üçüncü cümle aralık kullanıyor. @@ 4.1-4.3\n\nYeni paragraf cümlesi burada. @@ 2.2")
    assert [[text for text, _ in paragraph] for paragraph in parsed] == [
        ["Birinci cümle burada yazıldı.", "İkinci cümle de aynı satırda yazıldı.", "Üçüncü cümle aralık kullanıyor."],
        ["Yeni paragraf cümlesi burada."]]
    assert parsed[0][1][1] == [{"source": 1, "unit": 3}, {"source": 2, "unit": 1}]
    assert [e["unit"] for e in parsed[0][2][1]] == [1, 2, 3] and all("@@" not in text for p in parsed for text, _ in p)


def test_invalid_lines_are_dropped_and_a_draft_without_any_valid_line_is_rejected():
    parsed = free_answer._parse("Geçerli bir cümle burada yazıldı. @@ 1.1\nBu satırın atıf numarası yok.\n"
                                "Bu [1] köşeli parantez içeriyor. @@ 1.1\nhttps://x.example bağlantı. @@ 1.1")
    assert parsed == [[("Geçerli bir cümle burada yazıldı.", [{"source": 1, "unit": 1}])]]
    import pytest

    with pytest.raises(ValueError):
        free_answer._parse("Atıfsız bir cümle burada duruyor.\n\nBaşka atıfsız cümle.")



def test_the_answer_pool_gets_up_to_three_decisions_even_when_the_selector_kept_only_a_statute():
    from api.ai.pipeline import _with_decisions

    decisions = [court_decision_context(chunk_id=f"00000000-0000-0000-0000-0000000001{i}0",
                                        source_id=f"00000000-0000-0000-0000-0000000002{i}0") for i in range(5)]
    assert _with_decisions([LAW], [LAW, *decisions]) == [LAW, *decisions[:3]]
    assert _with_decisions([LAW, decisions[0]], [LAW, *decisions]) == [LAW, decisions[0], *decisions[1:3]]
    assert _with_decisions([LAW], [LAW]) == [LAW]


def test_a_slow_first_attempt_is_not_retried(monkeypatch):
    clock = iter([0.0, 50.0, 50.0, 50.0, 50.0])
    monkeypatch.setattr(free_answer, "monotonic", lambda: next(clock, 50.0))
    provider = Provider(DRAFT, verdict(3, approved=set()), DRAFT, verdict(3, approved=set()))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is None and info["attempts"] == 1 and len(provider.calls) == 2


def test_the_year_of_a_decision_date_or_docket_number_is_a_known_number():
    from api.ai.numeric_support import numeric_claims_supported as supported

    reference = "Yargıtay 6. Hukuk Dairesi, E. 2014/5973, K. 2014/7429, T. 05.06.2014"
    assert supported("Yargıtay 6. Hukuk Dairesi 2014 tarihli kararında temerrüt konusu işlenmiştir.", reference)
    assert not supported("Yargıtay 6. Hukuk Dairesi 2016 tarihli kararında temerrüt konusu işlenmiştir.", reference)
    assert not supported("Karar 7429 yılında verilmiştir.", "T. 05.06.2014")


def test_the_same_information_reworded_is_not_shown_twice():
    shown = ["Zamanaşımı süresi, zararı ve tazminat yükümlüsünü öğrendiğiniz tarihten itibaren iki yıldır."]
    assert free_answer._repeats("Zamanaşımı süresi zararı ve tazminat yükümlüsünü öğrendiğiniz tarihten itibaren iki yıldır;", shown)
    assert not free_answer._repeats("Sigortacıya karşı kesilen zamanaşımı yükümlü bakımından da kesilmiş olur.", shown)


def test_a_repaired_lead_never_talks_about_the_inner_workings():
    lead = "İşçinin isteyebileceği tazminat türleri doğrulanmış cümlelerde yer almamaktadır. @@ 2"
    provider = Provider(DRAFT, verdict(3, approved={2, 3}), lead, DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and "doğrulanmış" not in answer.text


def test_a_failed_first_attempt_is_retried_with_the_stronger_model():
    weak, strong = Provider(DRAFT, verdict(3, approved=set())), Provider(DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(weak, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info, stronger_provider=strong)
    assert answer is not None and info["attempts"] == 2 and len(weak.calls) == 2 and len(strong.calls) == 2


def test_a_draft_in_the_wrong_format_is_retried_with_a_format_reminder():
    provider = Provider("Atıfsız bir cümle burada duruyor.", DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 2
    assert "format_reminder" not in json.loads(provider.calls[0]["prompt"])
    assert "format_reminder" in json.loads(provider.calls[1]["prompt"])


def test_a_conclusion_lead_may_combine_proven_sentences_but_numbers_stay_hard():
    from api.ai import synthesis

    views = synthesis._source_views([LAW], 36000)
    evidence = [{"source": 1, "unit": 1}, {"source": 1, "unit": 2}]
    ok = synthesis._checked_claim(0, "Evet, hem bildirim süresine ait ücret tutarında tazminat hem de iki hafta kuralı birlikte uygulanır.",
                                  evidence, [LAW], views, lenient=True, conclusion=True)
    assert ok.text.startswith("Evet")
    import pytest

    with pytest.raises(synthesis._Rejected):
        synthesis._checked_claim(0, "Evet, bildirim süresi iki hafta değil dokuz haftadır.", evidence, [LAW], views,
                                 lenient=True, conclusion=True)


def test_source_numbers_written_on_the_line_below_the_sentence_still_count():
    parsed = free_answer._parse("Evet, ikisini birlikte talep edebilirsiniz.  \n@@ 1.1 2.4\n\n"
                                "Kıdem için bir yıl gerekir.\nÜç yıllık süreniz bunu karşılar.  \n@@ 1.1")
    assert [[text for text, _ in p] for p in parsed] == [
        ["Evet, ikisini birlikte talep edebilirsiniz."], ["Kıdem için bir yıl gerekir.", "Üç yıllık süreniz bunu karşılar."]]
    assert parsed[0][0][1] == [{"source": 1, "unit": 1}, {"source": 2, "unit": 4}]


def test_one_unsafe_sentence_in_an_evidence_block_does_not_erase_its_supported_neighbour():
    draft = RULE_1 + " Her koşulda 99999 TL ödeme alırsınız. @@ 1.1"
    answer, info, provider = run(draft, verdict(1), contexts=(LAW,))
    assert answer and answer.grounded and RULE_1 in answer.text
    assert "99999" not in answer.text
    assert info["draft_sentences"] == 2 and info["kept"] == 1
    assert info["sentence_outcomes"]["2"].startswith("kod:")
    assert len(provider.calls) == 2


def test_all_rejected_claims_still_supply_concrete_feedback_for_the_existing_retry():
    provider = Provider(DRAFT, verdict(3, approved=set()), DRAFT, verdict(3))
    info = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?",
                                  contexts=[LAW, DECISION], diagnostics=info)
    assert answer and answer.grounded and info["attempts"] == 2
    feedback = json.loads(provider.calls[2]["prompt"])["revision_feedback_not_evidence"]
    assert len(feedback["removed_sentences"]) == 3


def test_actual_checker_coverage_flag_is_not_ignored_when_all_claims_are_supported():
    incomplete = json.loads(verdict(3))
    incomplete["coverage_preserved"] = False
    provider = Provider(DRAFT, json.dumps(incomplete), DRAFT, verdict(3))
    info = {}
    answer = free_verified_answer(provider, question="Bildirim süresi ve koşulları nelerdir?",
                                  contexts=[LAW, DECISION], diagnostics=info)
    assert answer and answer.grounded and info["attempts"] == 2
    assert info["coverage_preserved"] is True and len(provider.calls) == 4
    assert "coverage_issue" in json.loads(provider.calls[2]["prompt"])["revision_feedback_not_evidence"]


def test_more_than_three_years_never_becomes_three_years_and_over():
    from api.ai.numeric_support import boundaries_supported as ok

    law = "İşi birbuçuk yıldan üç yıla kadar sürmüş işçi için altı hafta, üç yıldan fazla sürmüş işçi için sekiz haftadır."
    assert not ok("3 yıl ve üzeri çalışan işçi için bildirim süresi 8 haftadır.", law)
    assert not ok("En az 3 yıl çalışan işçi için bildirim süresi 8 haftadır.", law)
    assert ok("3 yıldan fazla çalışan işçi için bildirim süresi 8 haftadır.", law)
    assert ok("Bir buçuk yıldan üç yıla kadar çalışan işçi için süre altı haftadır.", law)
    assert not ok("Bir yıldan fazla çalışan işçi kıdem tazminatı alır.", "En az bir yıl çalışmış olan işçi kıdem tazminatı alır.")


def test_an_article_the_sources_do_not_contain_is_named_as_not_found_without_asking_the_model():
    from dataclasses import replace

    from api.ai.pipeline import _missing_requested_article as missing

    article_18 = replace(LAW, law_no="4857", article_no="18")
    assert missing("4857 sayılı İş Kanunu madde 999 neyi düzenler?", [article_18]) == ("4857", "999")
    assert missing("4857 sayılı İş Kanunu madde 18 neyi düzenler?", [article_18]) is None
    assert missing("Kıdem tazminatı şartları nelerdir?", []) is None


def test_only_a_question_without_any_legal_word_gets_the_not_legal_message():
    from api.ai.pipeline import _looks_non_legal

    assert _looks_non_legal("Bugün hava nasıl olacak ve en iyi pizza tarifi nedir?")
    assert not _looks_non_legal("Komşum bahçemdeki ağacı kesti, ne yapabilirim?")
    assert not _looks_non_legal("Patronum maaşımı 3 aydır yatırmıyor")
    assert not _looks_non_legal("İşveren beni çıkardı")


def test_a_broken_reference_does_not_leave_numbers_in_front_of_the_next_sentence():
    parsed = free_answer._parse("Birinci cümle burada yazıldı. @@ 2.3.c 2.4 İkinci cümle de burada yazıldı. @@ 1.1")
    assert [text for text, _ in parsed[0]] == ["Birinci cümle burada yazıldı.", "İkinci cümle de burada yazıldı."]


def test_the_plan_splits_a_question_and_falls_back_to_the_question_itself():
    good = Provider(json.dumps({"parts": [{"question": "Nafaka nasıl belirlenir?", "queries": ["Türk Medeni Kanunu nafaka"]},
                                          {"question": "Mal paylaşımı davası hangi sürede açılır?", "queries": ["mal rejimi tasfiye"]}]}))
    plan = free_answer.plan_question(good, "Nafaka nasıl belirlenir, mal paylaşımı hangi sürede açılır?")
    assert [text for text, _ in plan] == ["Nafaka nasıl belirlenir?", "Mal paylaşımı davası hangi sürede açılır?"]
    assert plan[0][1] == ("Türk Medeni Kanunu nafaka",)
    assert free_answer.plan_question(Provider("bozuk"), "Soru nedir?") == [("Soru nedir?", ("Soru nedir?",))]


def test_a_part_without_a_proven_sentence_is_named_instead_of_skipped():
    from dataclasses import replace

    other = replace(LAW, chunk_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000099"), content="Kamulaştırma bedeli ödenir.")
    provider = RoutedProvider(DRAFT, [[1, 2, 3], []])
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresi nedir, mal paylaşımı hangi sürede açılır?",
                                  contexts=[LAW, DECISION, other], diagnostics=info,
                                  parts=[("Bildirim süresi nedir?", frozenset({LAW.chunk_id, DECISION.chunk_id})),
                                         ("Mal paylaşımı hangi sürede açılır?", frozenset({other.chunk_id}))])
    assert answer is not None and info["uncovered_parts"] == ["Mal paylaşımı hangi sürede açılır?"]
    assert info["coverage_preserved"] is False and info["partial_answer"] is True
    assert info["attempts"] == 2
    assert answer.text.endswith("“Mal paylaşımı hangi sürede açılır”.")
    assert json.loads(provider.calls[0]["prompt"])["parts"][1]["sources"] == [3]


def test_a_planned_part_with_a_number_the_user_did_not_write_is_not_quoted():
    note = free_answer._uncovered_note(["Mal paylaşımı davası 10 yılda mı açılır?"], "Mal paylaşımı hangi sürede açılır?")
    assert "10" not in note and "bir bölümü" in note


def test_the_plan_runs_on_the_light_gemini_model_without_waiting_when_busy():
    from types import SimpleNamespace

    from api.ai.pipeline import _planner

    gemini = SimpleNamespace(cloud_ai_provider="gemini", cloud_ai_plan_model="gemini-3.1-flash-lite", cloud_ai_api_key="k")
    planner = _planner(gemini)
    assert planner is not None and planner.model == "gemini-3.1-flash-lite" and planner.busy_waits == ()
    assert _planner(SimpleNamespace(cloud_ai_provider="openrouter", cloud_ai_plan_model="", cloud_ai_api_key="k")) is None


def test_a_question_the_planner_finds_not_legal_gets_an_empty_plan():
    provider = Provider(json.dumps({"legal": False, "parts": []}))
    assert free_answer.plan_question(provider, "En iyi pizza tarifi nedir?") == free_answer.NOT_LEGAL == []


def test_a_sentence_about_what_the_sources_contain_is_not_shown():
    assert free_answer._ABOUT_SOURCES.search("Kaynaklarınızda en iyi pizza tarifine ilişkin bir bilgi bulunmuyor.")
    assert free_answer._ABOUT_SOURCES.search("Paylaşılan kaynaklarda bu konuda hüküm yoktur.")
    assert not free_answer._ABOUT_SOURCES.search("Kira bedeli TÜFE oranını geçemez.")


def test_a_short_sentence_already_said_inside_a_longer_one_is_a_repeat():
    lead = ["Dava açma süresi altmış gündür; ancak özel bir kanunda farklı bir süre öngörülmüşse öncelikle o süre uygulanır."]
    assert free_answer._repeats("Bu nedenle özel bir kanunda farklı bir süre öngörülmüşse öncelikle o süre uygulanır.", lead)
    assert not free_answer._repeats("Süre, yazılı bildirimin yapıldığı tarihi izleyen günden başlar.", lead)


def test_period_helpers_detect_a_requested_and_a_stated_period():
    from api.ai.free_answer import _asks_period, _states_period
    assert _asks_period("Boşanma sonrası mal rejiminin tasfiyesi davasının zamanaşımı süresi")
    assert _asks_period("İdari işlemin iptali davasında dava açma süresi ne kadardır")
    assert not _asks_period("Boşanma davasında çocuğun velayeti hangi esaslara göre belirlenir")
    assert _states_period("Dava, kararın kesinleşmesinden itibaren on yıl içinde açılır.")
    assert _states_period("Süre 60 gündür.")
    assert not _states_period("Zamanaşımı süresi yabancı mahkeme kararının kesinleştiği tarihten başlar.")


def test_progressive_shortcut_is_skipped_for_period_facets():
    from api.ai.pipeline import _PERIOD_FACET
    assert _PERIOD_FACET.search("mal rejiminin tasfiyesi davasının zamanaşımı süresi")
    assert not _PERIOD_FACET.search("iştirak nafakasının şartları")


def test_sentences_about_the_provided_sources_are_recognised():
    from api.ai.free_answer import _ABOUT_SOURCES
    assert _ABOUT_SOURCES.search("Sağlanan diğer kaynaklar ise sigorta acenteliğine ilişkindir ve konuyla ilgili değildir.")
    assert _ABOUT_SOURCES.search("Kaynaklarda bu konuda bir süre yer almıyor.")
    assert not _ABOUT_SOURCES.search("Mal rejimi tasfiyesi davası on yıl içinde açılır.")


def _two_parts(other):
    return [("Bildirim süresi nedir?", frozenset({LAW.chunk_id, DECISION.chunk_id})),
            ("Başvuru nasıl yapılır?", frozenset({other.chunk_id}))]


def _other_source():
    return legislation_context(chunk_id='00000000-0000-0000-0000-000000000095',
                               source_id='00000000-0000-0000-0000-000000000096', content='Başvuru yazılı dilekçe ile yapılır.')


def test_a_question_with_several_parts_writes_each_part_in_its_own_call():
    other = _other_source()
    provider = RoutedProvider(DRAFT, [[1, 2, 3], [4]])
    info: dict = {}
    free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?", contexts=[LAW, DECISION, other],
                                      parts=_two_parts(other), diagnostics=info, parallel_parts=True)
    writes = [c for c in provider.calls if c["system_instruction"] == free_answer.WRITE_INSTRUCTION]
    assert info["parallel_write"] == 2 and len(writes) == 2
    focus = sorted(json.loads(c["prompt"])["write_only_part"]["part"] for c in writes)
    assert focus == [1, 2]
    # every call sees all sources: a part may need a source found for another part
    assert all(len(json.loads(c["prompt"])["sources"]) == 3 for c in writes)


def test_a_part_that_comes_back_in_the_wrong_shape_falls_back_to_one_call_for_the_whole_answer():
    other = _other_source()

    class OnePartBroken(RoutedProvider):
        def generate(self, **kwargs):
            if kwargs["system_instruction"] == free_answer.WRITE_INSTRUCTION and "write_only_part" in kwargs["prompt"]:
                self.calls.append(kwargs)
                if json.loads(kwargs["prompt"])["write_only_part"]["part"] == 2:
                    return "Biçimsiz metin, kaynak bağlantısı yok."
                return self.draft
            return super().generate(**kwargs)

    provider = OnePartBroken(DRAFT, [[1, 2, 3], []])
    info: dict = {}
    answer = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                               contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics=info, parallel_parts=True)
    assert info.get("parallel_write_fallback") is True and "parallel_write" not in info
    assert answer is not None


class PartAwareProvider(RoutedProvider):
    """A checker that answers per call: every sentence of the call approved and covering all the parts it is asked about."""

    def __init__(self, draft, *, broken_part_check=False):
        super().__init__(draft, None)
        self.broken_part_check = broken_part_check

    def generate(self, **kwargs):
        if kwargs["system_instruction"] == free_answer.WRITE_INSTRUCTION:
            self.calls.append(kwargs)
            return self.draft
        payload = json.loads(kwargs["prompt"])
        self.calls.append(kwargs)
        if kwargs["system_instruction"] == free_answer._CROSS_PART_DUPLICATE_INSTRUCTION:
            return json.dumps({"duplicate_claims": getattr(self, "cross_duplicates", [])})
        count, parts = len(payload["claims"]), len(payload.get("question_parts", ()))
        if self.broken_part_check and parts == 1:
            return "not json"
        rows = [list(range(1, count + 1))] + [[] for _ in range(parts - 1)]
        return with_parts(verdict(count), rows)


def test_each_part_is_checked_in_its_own_call_and_the_verdicts_are_merged():
    other = _other_source()
    provider = PartAwareProvider(DRAFT)
    info: dict = {}
    answer = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                               contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics=info, parallel_parts=True)
    assert answer is not None and info["parallel_write"] == 2 and info["parallel_check"] == 2
    checks = provider.checker_calls()
    assert len(checks) == 2 and all(len(json.loads(c["prompt"])["question_parts"]) == 1 for c in checks)
    # sentence numbers are local to each call (1..n) but the merged outcome uses the draft's own numbers
    assert sorted(info["sentence_outcomes"]) == [str(n) for n in range(1, 7)]
    assert info["kept"] >= 1 and info.get("parallel_check_fallback") is None


def test_a_part_check_that_is_not_a_valid_verdict_falls_back_to_the_ordinary_single_check():
    other = _other_source()
    provider = PartAwareProvider(DRAFT, broken_part_check=True)
    info: dict = {}
    answer = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                               contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics=info, parallel_parts=True)
    assert info.get("parallel_check_fallback") is True and "parallel_check" not in info
    assert answer is not None
    assert len(provider.checker_calls()[-1:]) == 1 and len(json.loads(provider.checker_calls()[-1]["prompt"])["question_parts"]) == 2


def test_a_call_that_hangs_is_answered_by_its_duplicate_and_a_failing_copy_does_not_fail_the_call():
    import threading
    import time

    from api.ai.providers import AIProviderError

    class Slow:
        name, model = "test", "fixture"

        def __init__(self):
            self.n, self.lock = 0, threading.Lock()

        def generate(self, **kwargs):
            with self.lock:
                self.n += 1
                mine = self.n
            if mine == 1:
                time.sleep(2.0)  # the first copy is slow
                return "late"
            return "quick"

    slow = Slow()
    started = time.monotonic()
    assert free_answer._generate_hedged(slow, hedge_after=0.05, system_instruction="s", prompt="p") == "quick"
    assert time.monotonic() - started < 1.0 and slow.n == 2

    class FirstFails:
        name, model = "test", "fixture"

        def __init__(self):
            self.n = 0

        def generate(self, **kwargs):
            self.n += 1
            if self.n == 1:
                time.sleep(0.2)
                raise AIProviderError("busy")
            return "ok"

    assert free_answer._generate_hedged(FirstFails(), hedge_after=0.05, system_instruction="s", prompt="p") == "ok"

    class AllFail:
        name, model = "test", "fixture"

        def generate(self, **kwargs):
            raise AIProviderError("down")

    try:
        free_answer._generate_hedged(AllFail(), hedge_after=0.0, system_instruction="s", prompt="p")
    except AIProviderError:
        pass
    else:
        raise AssertionError("both copies failing must raise")


def test_a_part_written_with_a_blank_line_after_every_sentence_reads_as_one_paragraph():
    other = _other_source()
    spaced = f"{RULE_1} @@ 1.1\n\nİkinci cümle de aynı kuralı sürdürür. @@ 1.1\n\nÜçüncü cümle de ilgili ayrıntıdır. @@ 1.1"
    written = free_answer._write_parts_in_parallel(RoutedProvider(spaced, None), {"question": "q", "sources": []}, _two_parts(other))
    assert written is not None
    raw, starts = written
    assert starts == [1, 4]
    # inside each part there is no blank line left; the two parts are still separated by one
    assert raw.count("\n\n") == 1
    assert [len(p) for p in free_answer._parse(raw)] == [3, 3]



def test_an_article_ending_in_a_repealed_paragraph_note_is_still_usable_evidence():
    # TCK m. 73 ends "(8) (Mülga: 6/12/2006 – 5560/45 md.)" and the next article's heading; it was refused as a whole
    from dataclasses import replace
    body = ("Madde 73- (1) Şikayete bağlı suçta yetkili kimse altı ay içinde şikayette bulunmazsa soruşturma yapılamaz. "
            "(2) Bu süre failin kim olduğunun öğrenildiği günden başlar.\n(8) (Mülga: 6/12/2006 – 5560/45 md.)\n\nDava veya cezanın düşmesinin etkisi")
    context = replace(LAW, content=body)
    usable = free_answer._usable(context, 36000)
    assert usable is not None and "altı ay" in usable.content and "Mülga" not in usable.content


def test_clearly_unrelated_sources_are_dropped_but_never_a_whole_part_or_everything():
    from dataclasses import replace
    import uuid
    a, b, c = (replace(LAW, chunk_id=uuid.UUID(f"00000000-0000-0000-0000-0000000001{n}0"), content=f"Kaynak {n} metni burada yazılıdır.")
               for n in (1, 2, 3))

    class P:
        name, model = "test", "fixture"

        def __init__(self, answer):
            self.answer = answer

        def generate(self, **kwargs):
            return self.answer

    parts = [("Birinci?", frozenset({a.chunk_id})), ("İkinci?", frozenset({b.chunk_id, c.chunk_id}))]
    assert free_answer._drop_unrelated_sources(P('{"unrelated":[2]}'), "Soru?", [a, b, c], parts) == [2]
    # a part may not lose every one of its sources: [1] is part one's only source and stays
    assert free_answer._drop_unrelated_sources(P('{"unrelated":[1,2,3]}'), "Soru?", [a, b, c], parts) == []
    assert free_answer._drop_unrelated_sources(P("not json"), "Soru?", [a, b, c], parts) == []
    assert free_answer._drop_unrelated_sources(P('{"unrelated":[9,"x"]}'), "Soru?", [a, b, c], parts) == []
    assert free_answer._drop_unrelated_sources(P('{"unrelated":[1]}'), "Soru?", [a, b], parts) == []  # too few to judge


def test_checked_sentences_are_rebound_to_a_reordered_pool_and_dropped_when_their_unit_changed():
    from dataclasses import replace
    from api.ai import synthesis
    old_pool = [LAW, DECISION]
    old_views = synthesis._source_views(old_pool, 36000)
    flat = [("Birinci kanıtlı cümle.", [{"source": 1, "unit": 1}]), ("İkinci kanıtlı cümle.", [{"source": 2, "unit": 1}])]
    snapshot = free_answer._binding_snapshot(flat, old_pool, old_views)
    saved = [(text, snapshot[str(n)]) for n, (text, _) in enumerate(flat, 1)]

    new_pool = [DECISION, LAW]  # a revision interleaves sources: the old numbers now point at the wrong chunk
    new_views = synthesis._source_views(new_pool, 36000)
    rebound = free_answer._remap_preserved(saved, new_pool, new_views)
    assert [(p[0][0], p[0][1][0]["source"]) for p in rebound] == [("Birinci kanıtlı cümle.", 2), ("İkinci kanıtlı cümle.", 1)]

    changed = [replace(LAW, content=LAW.content + " Yeni bir cümle eklendi."), DECISION]
    changed_views = synthesis._source_views(changed, 36000)
    kept = free_answer._remap_preserved(saved, changed, changed_views)
    # the first unit of the changed source is still byte-identical (a sentence was only appended); a removed source drops its sentence
    assert [p[0][0] for p in kept] == ["Birinci kanıtlı cümle.", "İkinci kanıtlı cümle."]
    assert free_answer._remap_preserved(saved, [DECISION], synthesis._source_views([DECISION], 36000)) == [
        [("İkinci kanıtlı cümle.", [{"source": 1, "unit": 1}])]]


def test_sentences_approved_in_the_first_attempt_stay_approved_when_the_repeat_check_refuses_them():
    question = "Bildirim süresine uyulmazsa ne olur?"
    state: dict = {}
    first = free_answer._free_verified_answer(Provider(DRAFT, verdict(3)), question=question, contexts=[LAW, DECISION],
                                              repair_state=state, diagnostics={})
    assert first is not None and state["chunk_paragraphs"]
    new_sentence = f"{RULE_2} @@ 1.2"
    info: dict = {}
    # the repeat check approves only the new sentence (4th) and refuses the three it approved before
    second = free_answer._free_verified_answer(Provider(new_sentence, verdict(4, approved={4})), question=question,
                                               contexts=[LAW, DECISION], repair_state=state, diagnostics=info)
    assert second is not None and info["sticky_approved"] == 3
    for earlier in ("sözleşmeyi feshederse", "altı aydan kısa süren", "ihbar tazminatına hükmetmiştir"):
        assert earlier in second.text


def test_a_new_sentence_is_never_approved_by_the_stickiness():
    question = "Bildirim süresine uyulmazsa ne olur?"
    state: dict = {}
    free_answer._free_verified_answer(Provider(DRAFT, verdict(3)), question=question, contexts=[LAW, DECISION],
                                      repair_state=state, diagnostics={})
    info: dict = {}
    refused = "Bildirim süresi işi altı aydan az sürmüş işçi için iki haftadır ve sözleşmeyle artırılabilir. @@ 1.2"
    second = free_answer._free_verified_answer(Provider(refused, verdict(4, approved=set())), question=question,
                                               contexts=[LAW, DECISION], repair_state=state, diagnostics=info)
    # only the three earlier sentences remain; the refused new one is gone
    assert second is not None and "sözleşmeyle artırılabilir" not in second.text and info["sticky_approved"] == 3


def _claim(text, source=1):
    from api.ai import synthesis
    return synthesis._Claim(text=text, evidence=((source, "kanıt cümlesi"),))


def test_verified_parts_are_shown_in_part_order_even_when_a_later_part_is_checked_first():
    shown = []
    candidates = [(1, _claim("Birinci bölümün birinci cümlesi.")), (2, _claim("Birinci bölümün ikinci cümlesi.")),
                  (3, _claim("İkinci bölümün cümlesi.")), (4, _claim("İkinci bölümün reddedilen cümlesi."))]
    preview = free_answer._PartPreview(shown.append, candidates, [1, 1, 2, 2], [LAW], 2)
    valid = {"checker_protocol_status": "valid"}
    # part 2 (candidates 3 and 4; the checker approves only the first) is back before part 1 and must wait for it
    preview(1, [3, 4], verdict(2, approved={1}), valid)
    assert shown == []
    preview(0, [1, 2], verdict(2), valid)
    assert len(shown) == 1
    text = shown[0].text
    assert text.index("Birinci bölümün birinci") < text.index("Birinci bölümün ikinci") < text.index("İkinci bölümün cümlesi")
    assert "reddedilen" not in text and shown[0].contexts == (LAW,)


def test_a_part_whose_check_was_not_valid_is_skipped_without_blocking_the_next_part():
    shown = []
    candidates = [(1, _claim("Birinci bölüm cümlesi.")), (2, _claim("İkinci bölüm cümlesi."))]
    preview = free_answer._PartPreview(shown.append, candidates, [1, 2], [LAW], 2)
    preview(0, [1], "bozuk", {"checker_protocol_status": "invalid_json"})
    preview(1, [2], verdict(1), {"checker_protocol_status": "valid"})
    assert len(shown) == 1 and "İkinci bölüm" in shown[0].text and "Birinci bölüm" not in shown[0].text


def test_a_part_with_no_sentence_does_not_hold_back_the_parts_after_it():
    shown = []
    candidates = [(1, _claim("Tek cümle burada."))]
    preview = free_answer._PartPreview(shown.append, candidates, [1], [LAW], 2)
    preview(0, [], None, {})
    preview(1, [1], verdict(1), {"checker_protocol_status": "valid"})
    assert len(shown) == 1 and "Tek cümle" in shown[0].text


def test_the_parallel_check_reports_verified_parts_to_the_caller_and_the_final_answer_contains_them():
    other = _other_source()
    shown = []
    provider = PartAwareProvider(DRAFT)
    answer = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                               contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics={},
                                               parallel_parts=True, on_partial=shown.append)
    assert answer is not None and shown
    # every verified sentence that was shown early is in the final answer
    final_sentences = {s.strip() for s in answer.text.replace("\n", " ").split(". ") if s.strip()}
    for early in shown:
        for sentence in (s.strip().rstrip(".") for s in early.text.replace("\n", " ").split(". ") if s.strip()):
            assert sentence.rstrip(".") in answer.text


def test_the_first_attempts_verified_answer_is_offered_before_a_second_attempt_starts(monkeypatch):
    from api.ai.verification import VerifiedAnswer
    calls, offered = [], []

    def attempt(provider, **kwargs):
        calls.append(True)
        first = len(calls) == 1
        kwargs["diagnostics"].update(coverage_preserved=not first, kept=3, lead_removed=first, draft_sentences=4)
        return VerifiedAnswer("birinci deneme" if first else "ikinci deneme", (LAW,), ())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    answer = free_answer.free_verified_answer(object(), question="Soru?", contexts=[LAW], on_partial=offered.append)
    assert answer.text == "ikinci deneme" and [a.text for a in offered] == ["birinci deneme"]


def test_reasons_for_refused_sentences_are_asked_for_separately_and_parsed_by_sentence_number():
    from api.ai import synthesis

    class Explainer:
        name, model = "test", "fixture"

        def __init__(self, answer):
            self.answer, self.prompts = answer, []

        def generate(self, **kwargs):
            self.prompts.append(json.loads(kwargs["prompt"]))
            return self.answer

    refused = [(2, _claim("Reddedilen cümle.")), (5, _claim("Bir başkası."))]
    views = synthesis._source_views([LAW], 36000)
    good = Explainer('{"reasons":[{"id":2,"why":"ifade_duzelt: koşul düşmüş"},{"id":5,"why":"kaynak_eksik: dayanak yok"}]}')
    assert free_answer._explain_rejections(good, "Soru?", refused, views) == {
        "2": "ifade_duzelt: koşul düşmüş", "5": "kaynak_eksik: dayanak yok"}
    assert [c["id"] for c in good.prompts[0]["rejected_claims"]] == [2, 5]
    assert free_answer._explain_rejections(Explainer("not json"), "Soru?", refused, views) == {}
    assert free_answer._explain_rejections(Explainer("{}"), "Soru?", [], views) == {}


def test_the_deferred_check_instruction_does_not_ask_for_prose_reasons():
    assert '"why" alanı YAZMA' in free_answer.LEAD_CHECK_INSTRUCTION_DEFERRED
    assert '"why" alanı YAZMA' not in free_answer.LEAD_CHECK_INSTRUCTION
    assert free_answer.LEAD_CHECK_INSTRUCTION_DEFERRED.startswith(free_answer.synthesis.CHECK_INSTRUCTION)


def test_a_retry_waits_for_the_background_reasons_and_hands_them_to_the_rewrite(monkeypatch):
    from concurrent.futures import Future
    from api.ai.verification import VerifiedAnswer
    calls, feedback = [], []

    def attempt(provider, **kwargs):
        calls.append(True)
        feedback.append(dict(kwargs.get("revision_feedback") or {}))
        first = len(calls) == 1
        if first:
            reasons = Future()
            reasons.set_result({"2": "ifade_duzelt: süre sınırı düşmüş"})
            kwargs["repair_state"]["explain_future"] = reasons
        kwargs["diagnostics"].update(coverage_preserved=not first, kept=3, lead_removed=first, draft_sentences=4,
                                     debug_removed={"2": "Atılan cümle."} if first else {},
                                     sentence_outcomes={"2": "denetçi_reddetti"} if first else {})
        return VerifiedAnswer("birinci" if first else "ikinci", (LAW,), ())

    monkeypatch.setattr(free_answer, "_free_verified_answer", attempt)
    free_answer.free_verified_answer(object(), question="Soru?", contexts=[LAW])
    assert len(calls) == 2
    assert feedback[1]["checker_findings"] == {"2": "ifade_duzelt: süre sınırı düşmüş"}
    assert feedback[1]["repair_types"] == {"2": "wording_or_condition"}


def test_a_sentence_repeated_under_another_part_is_removed_once_the_independent_pass_says_so():
    other = _other_source()
    provider = PartAwareProvider(DRAFT)
    baseline: dict = {}
    first = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                              contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics=baseline, parallel_parts=True)
    assert first is not None and baseline.get("semantic_repeated_removed", 0) == 0
    assert baseline.get("semantic_repeated_removed", 0) == 0

    provider = PartAwareProvider(DRAFT)
    provider.cross_duplicates = [{"id": 6, "duplicate_of": 1}]
    info: dict = {}
    second = free_answer._free_verified_answer(provider, question="Süre nedir, başvuru nasıl yapılır?",
                                               contexts=[LAW, DECISION, other], parts=_two_parts(other), diagnostics=info, parallel_parts=True)
    assert second is not None and info["semantic_repeated_removed"] == 1


def _incomplete(count):
    value = json.loads(verdict(count))
    value["coverage_preserved"] = False
    return json.dumps(value)


def test_a_sizeable_single_part_answer_the_checker_calls_incomplete_is_not_rewritten(monkeypatch):
    # Measured 2026-10-31: a second attempt after "not complete" over 13 proven sentences repeated the same verdict (+30 s).
    monkeypatch.setattr(free_answer, "_MIN_SENTENCES_FOR_FINAL", 2)
    provider = Provider(DRAFT, _incomplete(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 1 and info["partial_answer"] is True and len(provider.calls) == 2


def test_a_small_single_part_answer_the_checker_calls_incomplete_is_still_rewritten(monkeypatch):
    monkeypatch.setattr(free_answer, "_MIN_SENTENCES_FOR_FINAL", 5)
    provider = Provider(DRAFT, _incomplete(3), DRAFT, verdict(3))
    info: dict = {}
    answer = free_verified_answer(provider, question="Bildirim süresine uyulmazsa ne olur?", contexts=[LAW, DECISION],
                                  diagnostics=info)
    assert answer is not None and info["attempts"] == 2
