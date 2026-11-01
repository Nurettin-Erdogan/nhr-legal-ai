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
