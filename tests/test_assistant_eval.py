"""Evaluation must be offline by default and must never silently overspend."""
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys

import pytest

from scripts.assistant_eval import Budget, CASES, EFFORTS, EvaluationStop, positive_decimal, score, summarize


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "bad"])
def test_invalid_budget_is_rejected(amount):
    with pytest.raises(ValueError):
        positive_decimal(amount)


def test_budget_stops_before_dispatch_and_unknown_cost_uses_reservation():
    budget = Budget("0.1")
    held = budget.reserve("0.08")
    with pytest.raises(EvaluationStop):
        budget.reserve("0.03")
    budget.settle(held)
    assert budget.spent == Decimal("0.08")
    assert budget.held == 0


def test_zero_cost_is_valid_and_over_reservation_is_fatal():
    budget = Budget("0.1")
    held = budget.reserve("0.02")
    budget.settle(held, "0")
    assert budget.spent == 0
    held = budget.reserve("0.02")
    with pytest.raises(EvaluationStop):
        budget.settle(held, "0.03")
    assert budget.held == held


def test_budget_reservations_are_safe_across_threads():
    budget = Budget("0.10")
    def reserve(_):
        try:
            return budget.reserve("0.01")
        except EvaluationStop:
            return Decimal(0)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(100)))
    assert sum(results) == budget.held == Decimal("0.10")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_each_case_has_public_question_facet_rubric_and_reference_pairs(case):
    assert case["question"] and len(case["question"]) < 2000
    assert len(case["facets"]) >= 2
    assert all(len(ref) == 2 for ref in case["refs"])
    answer = {"grounded": True, "answer": "Örnek", "citations": [
        {"law_no": law, "article_no": article, "verification": "official"} for law, article in case["refs"]]}
    result = score(case, answer)
    assert result["automatic_source_checks_pass"] is True
    assert result["legal_correctness"] == "not_established_by_automatic_checks"
    assert set(result["expert_review"].values()) == {"pending"}
    answer["citations"][0]["verification"] = "third_party"
    assert score(case, answer)["automatic_source_checks_pass"] is False


def test_expected_law_and_article_must_be_in_same_citation():
    answer = {"grounded": True, "answer": "6098 m.344", "citations": [
        {"law_no": "6098", "article_no": "315", "verification": "official"},
        {"law_no": "4857", "article_no": "344", "verification": "official"}]}
    assert score(CASES[0], answer)["missing_expected_refs"] == [["6098", "344"]]


def test_summary_does_not_treat_coverage_flag_or_keywords_as_legal_correctness():
    rows = [{"effort": e, "seconds": 1, "cost_usd": "0.001", "score": score(CASES[0], {
        "answer": "artış sınırı beş yıl istisnası", "grounded": True, "citations": []})} for e in EFFORTS]
    assert all(s["automatic_source_passes"] == 0 and s["expert_review"] == "pending" for s in summarize(rows).values())


def test_source_pass_does_not_hide_partial_answer_or_refusal():
    row = {"effort": "medium", "seconds": 1, "cost_usd": "0.001",
           "score": {"automatic_source_checks_pass": True},
           "answer": {"answer_kind": "insufficient_sources"},
           "timings": {"extra": {"free_answer": {"partial_answer": True, "coverage_preserved": False}}}}
    result = summarize([row])["medium"]
    assert result["automatic_source_passes"] == 1
    assert result["partial_answers"] == result["checker_coverage_false"] == result["refusals"] == 1


def test_default_cli_prints_matrix_without_live_settings_or_network():
    completed = subprocess.run([sys.executable, "-X", "utf8", "scripts/assistant_eval.py"],
                               capture_output=True, encoding="utf-8", check=True)
    plan = json.loads(completed.stdout)
    assert plan["paid_calls"] == 0
    assert len(plan["cases"]) == 10
    assert plan["efforts"] == ["low", "medium", "high"]


def test_live_requires_new_path_and_explicit_budget(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("{}")
    completed = subprocess.run([sys.executable, "scripts/assistant_eval.py", "--live", "--output", str(path)],
                               capture_output=True, check=False)
    assert completed.returncode == 2
    assert path.read_text() == "{}"


@pytest.mark.parametrize("budget,expected_calls", [("0.001", 0), ("0.10", 6)])
def test_live_meter_covers_writer_and_auxiliary_and_stops_before_request(monkeypatch, tmp_path, budget, expected_calls):
    import asyncio
    from dataclasses import dataclass
    from types import SimpleNamespace
    import httpx
    from api import config
    from api.ai import pipeline
    from api.ai.cloud_provider import _CloudBase, OpenRouterDeepSeekProvider
    from scripts.assistant_eval import live, MODEL

    @dataclass
    class Settings:
        cloud_ai_provider: str = "openrouter"
        cloud_ai_model: str = MODEL
        official_web_research_enabled: bool = True

    @dataclass
    class Timing:
        llm_ms: float = 1

    settings, calls = Settings(), []
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)

    class CatalogClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url):
            assert url == "https://openrouter.ai/api/v1/models"
            return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [
                {"id": MODEL, "pricing": {"prompt": "0.0000001", "completion": "0.0000005", "web_search": "0.01"}}]})

    monkeypatch.setattr(httpx, "Client", CatalogClient)
    def post(self, url, headers, payload):
        assert payload["max_tokens"] == 16384
        calls.append(payload["reasoning"])
        return {"choices": [{"message": {"content": "Test"}, "finish_reason": "stop"}],
                "usage": {"cost": 0.001, "prompt_tokens": 10, "completion_tokens": 10}}
    monkeypatch.setattr(_CloudBase, "_post", post)

    async def execute(request, user):
        assert user is None and request.conversation_id is None
        assert pipeline.get_settings().official_web_research_enabled is False
        provider = OpenRouterDeepSeekProvider(model=MODEL, api_key="not-a-real-key", reasoning_effort=request.reasoning_effort)
        provider.generate(system_instruction="Source-based writer", prompt="Synthetic")
        provider.generate_auxiliary(system_instruction="Source checker", prompt="Synthetic")
        return SimpleNamespace(model_dump=lambda **kw: {"answer": "Test", "grounded": False, "citations": []}), Timing()
    monkeypatch.setattr(pipeline, "execute_answer", execute)
    output = tmp_path / "report.json"
    code = asyncio.run(live(SimpleNamespace(budget_usd=budget, limit=1, output=output)))
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(calls) == expected_calls
    if expected_calls:
        assert code == 0
        assert calls == [{"effort": "low"}, {"enabled": False}, {"effort": "medium"},
                         {"enabled": False}, {"effort": "high"}, {"enabled": False}]
        assert Decimal(report["spent_usd"]) == Decimal("0.006")
    else:
        assert code == 2 and report["stopped"] == "budget_before_call"
    assert "not-a-real-key" not in output.read_text(encoding="utf-8")
    assert settings.official_web_research_enabled is True
def test_selected_matrix_preserves_explicit_effort_and_case_scope():
    from types import SimpleNamespace
    from scripts.assistant_eval import selected_matrix
    cases, efforts = selected_matrix(SimpleNamespace(case=["leave", "administrative"], effort=["low", "low"], limit=10))
    assert [c["id"] for c in cases] == ["administrative", "leave"]
    assert efforts == ("low",)

