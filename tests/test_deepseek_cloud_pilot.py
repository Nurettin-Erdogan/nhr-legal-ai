"""DeepSeek Flash pilot: yalnız MockTransport; ücretli API/ağ çağrısı yok."""

import json
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from api.ai.cloud_provider import DeepSeekCloudProvider, create_cloud_provider
from api.ai.pipeline import answer_provider
from api.ai.providers import AIProviderError
from api.schemas import AIAnswerRequest


def reply(content="Sonuç.", finish="stop", **message_extra):
    return {"choices": [{"message": {"content": content, **message_extra}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 150}}


@pytest.mark.parametrize("effort", ["none", "low", "high", "max"])
def test_explicit_thinking_mode_and_bounded_output(effort):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply(reasoning_content="INTERNAL_NOT_FOR_USER"))

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", reasoning_effort=effort,
                                    max_output_tokens=4096, transport=httpx.MockTransport(handler))
    assert provider.generate(system_instruction="Yalnız JSON döndür.", prompt="Deneme") == "Sonuç."
    body = seen[0]
    assert body["thinking"] == {"type": "disabled" if effort == "none" else "enabled"}
    assert body["reasoning_effort"] == effort
    assert body["max_tokens"] == 4096
    assert body["response_format"] == {"type": "json_object"}
    assert "temperature" not in body and "tools" not in body
    assert provider.last_usage.eval_count == 150
    assert "test-only" not in repr(provider)


def test_invalid_effort_fails_before_network():
    with pytest.raises(AIProviderError, match="düşünme seviyesi"):
        create_cloud_provider(provider_name="deepseek", model="", api_key="test-only", reasoning_effort="surprise")


def test_provider_does_not_silently_drop_deepseek_reasoning_setting():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "unsupported reasoning_effort"}})

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
                                    transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError):
        provider.generate(system_instruction="s", prompt="p")
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 402, 429, 503])
def test_remote_failure_does_not_retry_or_reveal_body(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "SECRET_BODY"}})

    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
                                    transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError) as error:
        provider.generate(system_instruction="s", prompt="p")
    assert "SECRET_BODY" not in str(error.value) and "test-only" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize("finish", ["length", "content_filter", "tool_calls", None])
def test_unfinished_output_is_not_a_completed_answer(finish):
    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply(finish=finish))))
    with pytest.raises(AIProviderError):
        provider.generate(system_instruction="s", prompt="p")


def test_reasoning_only_output_is_never_used_as_answer():
    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply(
            content=None, reasoning_content="INTERNAL_NOT_FOR_USER"))))
    with pytest.raises(AIProviderError) as error:
        provider.generate(system_instruction="s", prompt="p")
    assert "INTERNAL_NOT_FOR_USER" not in str(error.value)


def test_failed_request_does_not_reuse_previous_usage():
    results = iter([httpx.Response(200, json=reply()), httpx.Response(402)])
    provider = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
                                    transport=httpx.MockTransport(lambda _: next(results)))
    provider.generate(system_instruction="s", prompt="p")
    assert provider.last_usage is not None
    with pytest.raises(AIProviderError):
        provider.generate(system_instruction="s", prompt="p")
    assert provider.last_usage is None


def test_routing_passes_explicit_deepseek_effort():
    settings = SimpleNamespace(cloud_ai_provider="deepseek", cloud_ai_model="deepseek-flash",
        cloud_ai_api_key="test-only", cloud_ai_timeout_seconds=90, cloud_ai_max_output_tokens=4096,
        cloud_ai_reasoning_effort="high")
    local = SimpleNamespace(name="qwen", model="local")
    provider = answer_provider(settings, AIAnswerRequest(question="Genel araştırma sorusu"), local)
    assert provider.primary.reasoning_effort == "high"
    assert provider.primary.max_output_tokens == 4096


def test_deepseek_config_defaults_have_no_app_output_cap_and_key_is_not_in_repr(monkeypatch):
    from api import config

    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setattr(config, "dotenv_values", lambda _: {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://test-only")
    monkeypatch.setenv("CLOUD_AI_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-real")
    for key in ("CLOUD_AI_MODEL", "CLOUD_AI_MAX_OUTPUT_TOKENS", "CLOUD_AI_TIMEOUT_SECONDS",
                "CLOUD_AI_REASONING_EFFORT"):
        monkeypatch.delenv(key, raising=False)
    config.get_settings.cache_clear()
    try:
        settings = config.get_settings()
        assert settings.cloud_ai_model == "deepseek-flash"
        assert settings.cloud_ai_max_output_tokens == 0
        assert settings.cloud_ai_timeout_seconds == 90
        assert settings.cloud_ai_reasoning_effort == "low"
        assert "test-key-not-real" not in repr(settings)
    finally:
        config.get_settings.cache_clear()


def test_pipeline_does_not_cache_local_fallback_as_deepseek(monkeypatch):
    from api.ai import pipeline
    from api.ai.cache import answer_cache
    from tests.factories import court_decision_context
    from tests.test_ai_pipeline import _settings

    answer_cache.clear()
    calls = []

    def handler(_):
        calls.append(1)
        return httpx.Response(402)

    cloud = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only",
                                 transport=httpx.MockTransport(handler))
    context = court_decision_context()

    class Local:
        name = "qwen"
        model = "local-qwen"

        def generate(self, **_):
            return "İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır. [K1]"

    monkeypatch.setattr(pipeline, "get_settings", lambda: _settings(cloud_ai_provider="deepseek",
        cloud_ai_model="deepseek-flash", cloud_ai_api_key="test-only", cloud_ai_timeout_seconds=90,
        cloud_ai_max_output_tokens=4096))
    monkeypatch.setattr(pipeline, "create_provider", lambda **_: Local())
    monkeypatch.setattr(pipeline, "create_cloud_provider", lambda **_: cloud)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *_, **__: [context])
    monkeypatch.setattr(pipeline, "generate_grounded_answer",
                        lambda provider, **_: provider.generate(system_instruction="s", prompt="p"))
    request = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")
    try:
        first, _ = asyncio.run(pipeline.execute_answer(request, None))
        second, _ = asyncio.run(pipeline.execute_answer(request, None))
        assert first.grounded and second.grounded
        assert first.provider == "qwen" and first.model == "local-qwen"
        assert not first.from_cache and not second.from_cache
        assert len(calls) == 2
    finally:
        answer_cache.clear()
