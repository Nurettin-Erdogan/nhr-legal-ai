import json

from api.ai.synthesis import synthesize_answer
from tests.factories import legislation_context
from tests.test_synthesis import Provider, approved, draft


def test_structured_repair_uses_explicit_auxiliary_and_keeps_checker_separate():
    quote = "Başvuru ancak tebliğ halinde yapılır."
    writer = Provider(draft("Başvuru yapılır.", (1, quote)))
    repair = Provider(draft(quote, (1, quote)))
    checker = Provider(approved())
    calls = []
    result = synthesize_answer(writer, repair_provider=repair, checker_provider=checker,
        question="Başvuru nasıl yapılır?", contexts=[legislation_context(content=quote)],
        semantic_repair=True, _generation_calls=calls)
    assert result and result.grounded
    assert len(writer.calls) == len(repair.calls) == len(checker.calls) == 1
    assert [c["stage"] for c in calls] == ["draft", "repair", "check"]
    assert all(c["completed"] and c["milliseconds"] >= 0 for c in calls)
    assert quote not in json.dumps(calls)  # telemetry contains no source/prompt text


def test_one_repair_budget_is_shared_by_mechanical_and_semantic_paths_without_diagnostics():
    quote = "Başvuru ancak tebliğ halinde yapılır."
    writer = Provider(draft("Başvuru yapılır.", (1, quote)), draft(quote, (1, quote)))
    verdict = approved()
    verdict["claims"][0]["supported"] = False
    checker = Provider(verdict)
    result = synthesize_answer(writer, checker_provider=checker, question="Başvuru nasıl yapılır?",
        contexts=[legislation_context(content=quote)], semantic_repair=True)
    assert result is None
    assert len(writer.calls) == 2 and len(checker.calls) == 1


def test_dropped_main_claim_is_repaired_before_checker_instead_of_publishing_fragment():
    rule = "Başvuru süresi tebliğ tarihinden başlar."
    condition = "Başvuru ancak yazılı bildirim halinde yapılır."
    context = legislation_context(content=rule + " " + condition)
    first = {"claims": [
        {"text": rule, "evidence": [{"source": 1, "quote": rule}]},
        {"text": "Başvuru yapılır.", "evidence": [{"source": 1, "quote": condition}]},
    ]}
    revised = {"claims": [
        {"text": rule, "evidence": [{"source": 1, "quote": rule}]},
        {"text": condition, "evidence": [{"source": 1, "quote": condition}]},
    ]}
    writer, repair, checker = Provider(first), Provider(revised), Provider(approved(2))
    calls = []
    answer = synthesize_answer(writer, repair_provider=repair, checker_provider=checker,
        question="Başvuru hangi şartla ve ne zaman yapılır?", contexts=[context],
        semantic_repair=True, _generation_calls=calls)
    assert answer and answer.grounded and condition in answer.text and rule in answer.text
    assert [call["stage"] for call in calls] == ["draft", "repair", "check"]
    assert len(json.loads(checker.calls[0]["prompt"])["claims"]) == 2


def test_coverage_repair_cannot_replace_missing_conditions_with_invented_deadline():
    rule = "Başvuru süresi tebliğ tarihinden başlar."
    condition = "Başvuru ancak yazılı bildirim halinde yapılır."
    context = legislation_context(content=rule + " " + condition)
    first = {"claims": [
        {"text": rule, "evidence": [{"source": 1, "quote": rule}]},
        {"text": "Başvuru yapılır.", "evidence": [{"source": 1, "quote": condition}]},
    ]}
    writer, repair, checker = Provider(first), Provider(draft("Başvuru kırk gün içinde yapılır.", (1, rule))), Provider()
    answer = synthesize_answer(writer, repair_provider=repair, checker_provider=checker,
        question="Başvuru şartı ve süresi?", contexts=[context], semantic_repair=True)
    assert answer is None and checker.calls == []
    assert len(writer.calls) == len(repair.calls) == 1


def test_source_gap_flag_does_not_skip_enabled_repair_of_a_dropped_legal_claim():
    quote = "Başvuru ancak yazılı bildirim halinde yapılır."
    bad = draft("Başvuru yapılır.", (1, quote))
    bad["source_gap"] = True
    writer, repair, checker = Provider(bad), Provider(draft(quote, (1, quote))), Provider(approved())
    calls = []
    result = synthesize_answer(writer, repair_provider=repair, checker_provider=checker,
        question="Başvurunun şartı nedir?", contexts=[legislation_context(content=quote)],
        semantic_repair=True, _generation_calls=calls)
    assert result and result.grounded and quote in result.text
    assert [item["stage"] for item in calls] == ["draft", "repair", "check"]
    assert len(json.loads(checker.calls[0]["prompt"])["claims"]) == 1
