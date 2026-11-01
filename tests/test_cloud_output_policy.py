"""Yanıt kotası yok; yalnız sağlayıcının teknik sınırları. Gerçek API çağrısı yapılmaz."""

import json

import httpx
import pytest

from api import config
from api.ai.cloud_provider import DEEPSEEK_MAX_COMPLETION_TOKENS, DeepSeekCloudProvider
from api.ai.providers import AIProviderError


def reply(text="Tam yanıt", finish="stop"):
    return {"choices": [{"message": {"content": text, "reasoning_content": "INTERNAL"}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}}


@pytest.mark.parametrize("auxiliary", [False, True])
@pytest.mark.parametrize("effort", ["none", "low", "max"])
def test_uncapped_main_and_helper_omit_application_token_limit(auxiliary, effort):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply())

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", reasoning_effort=effort,
        timeout_seconds=90, transport=httpx.MockTransport(handler))
    generate = provider.generate_auxiliary if auxiliary else provider.generate
    assert generate(system_instruction="Yalnız JSON döndür.", prompt="Kimlik 12345678901") == "Tam yanıt"
    assert len(seen) == 1 and "max_tokens" not in seen[0]
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["reasoning_effort"] == ("none" if auxiliary else effort)
    assert "12345678901" not in json.dumps(seen[0])
    assert provider.max_output_tokens == 0 and provider.reasoning_effort == effort
    assert provider.last_usage.num_predict is None


@pytest.mark.parametrize("auxiliary", [False, True])
@pytest.mark.parametrize("partial", ["Yarım yanıt", ""])
def test_default_length_retries_full_request_once_at_technical_capacity(auxiliary, partial):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply(partial, "length") if len(seen) == 1 else reply())

    provider = DeepSeekCloudProvider(model="deepseek-v4-pro", api_key="test-only", reasoning_effort="max",
        transport=httpx.MockTransport(handler))
    generate = provider.generate_auxiliary if auxiliary else provider.generate
    assert generate(system_instruction="Kaynaklara dayan.", prompt="Soru") == "Tam yanıt"
    assert len(seen) == 2 and "max_tokens" not in seen[0]
    assert seen[1]["max_tokens"] == DEEPSEEK_MAX_COMPLETION_TOKENS
    assert seen[1]["messages"] == seen[0]["messages"]
    assert seen[1]["thinking"] == seen[0]["thinking"]
    assert provider.last_usage.prompt_eval_count == 20 and provider.last_usage.eval_count == 40
    assert provider.last_usage.done_reason == "stop"
    assert provider.max_output_tokens == 0  # sonraki soru yeniden varsayılandan başlar


def test_second_length_stays_an_error_and_never_loops_or_concatenates_partial_json():
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(200, json=reply('{"half":', "length"))

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError) as error:
        provider.generate(system_instruction="Yalnız JSON döndür.", prompt="p")
    assert len(seen) == 2 and error.value.partial == '{"half":'
    assert "INTERNAL" not in error.value.partial
    assert provider.last_usage.done_reason == "length" and provider.last_usage.eval_count == 40


@pytest.mark.parametrize("finish", ["content_filter", "tool_calls", "aborted", None])
def test_no_retry_for_other_incomplete_reasons(finish):
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(200, json=reply(finish=finish))

    with pytest.raises(AIProviderError):
        DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", transport=httpx.MockTransport(handler)).generate(
            system_instruction="s", prompt="p")
    assert len(seen) == 1


def test_explicit_server_token_override_remains_explicit():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply(finish="length"))

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", max_output_tokens=32768,
        transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError):
        provider.generate(system_instruction="s", prompt="p")
    assert len(seen) == 1 and seen[0]["max_tokens"] == 32768


@pytest.mark.parametrize("value,expected", [("0", 0), ("1", 1), ("65536", 65536), ("999999", 393216)])
@pytest.mark.parametrize("name", ["CLOUD_AI_MAX_OUTPUT_TOKENS", "DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS"])
def test_config_does_not_reapply_old_small_caps(monkeypatch, name, value, expected):
    monkeypatch.setenv(name, value)
    assert config._cloud_output_tokens(name, deepseek=True) == expected


@pytest.mark.parametrize("value", [-1, 393217])
def test_invalid_provider_values_fail_before_network(value):
    with pytest.raises(AIProviderError, match="teknik aralığında"):
        DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", max_output_tokens=value)
