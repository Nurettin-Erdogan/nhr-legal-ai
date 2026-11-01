from types import SimpleNamespace

import pytest

from api.ai.llm_meter import LLMMeter, MeteredProvider, metered
from api.ai.providers import OllamaProvider


class Fake:
    last_usage = SimpleNamespace(prompt_eval_count=11, eval_count=7)

    def __init__(self, fail=False):
        self.fail = fail

    def generate(self, **kwargs):
        if self.fail:
            raise RuntimeError("provider down")
        return "cevap"


def test_calls_sizes_and_reported_tokens_are_counted_without_storing_any_text():
    meter = LLMMeter()
    provider = MeteredProvider(Fake(), meter)
    assert provider.generate(system_instruction="abc", prompt="defg") == "cevap"
    summary = meter.summary()
    assert summary["calls"] == 1 and summary["errors"] == 0 and summary["prompt_chars"] == 7 and summary["output_chars"] == 5
    assert summary["prompt_tokens"] == 11 and summary["output_tokens"] == 7
    assert "abc" not in str(summary) and "cevap" not in str(summary)


def test_a_failing_call_is_counted_and_still_raises():
    meter = LLMMeter()
    with pytest.raises(RuntimeError):
        MeteredProvider(Fake(fail=True), meter).generate(system_instruction="s", prompt="p")
    assert meter.summary()["calls"] == 1 and meter.summary()["errors"] == 1


def test_attributes_pass_through_and_local_providers_are_not_wrapped():
    meter = LLMMeter()
    assert MeteredProvider(Fake(), meter).last_usage.eval_count == 7
    local = OllamaProvider.__new__(OllamaProvider)
    assert metered(local, meter) is local and metered(None, meter) is None
