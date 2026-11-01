"""Explicit cloud-only generation: no model/network calls in these tests."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.ai import pipeline, providers
from api.ai.cloud_provider import BedrockProvider, FallbackProvider
from api.schemas import AIAnswerRequest


def settings(**values):
    return SimpleNamespace(**{
        "ai_provider": "bedrock", "cloud_ai_provider": "bedrock",
        "cloud_ai_api_key": "synthetic-test-key", "cloud_ai_timeout_seconds": 30,
        "cloud_ai_max_output_tokens": 2048, "cloud_ai_reasoning_effort": "low",
        **values,
    })


def test_primary_bedrock_constructs_no_local_fallback(monkeypatch):
    monkeypatch.setattr("api.config.get_settings", lambda: settings())
    monkeypatch.setattr(providers, "OllamaProvider", Mock(side_effect=AssertionError("local model")))
    provider = providers.create_provider(provider_name="bedrock", model="deepseek.v3.2")
    assert isinstance(provider, BedrockProvider)
    assert not isinstance(provider, FallbackProvider)
    assert provider.model == "deepseek.v3.2"


@pytest.mark.parametrize("values", [{"cloud_ai_provider": "openrouter"}, {"cloud_ai_api_key": ""}])
def test_missing_bedrock_configuration_fails_closed(monkeypatch, values):
    monkeypatch.setattr("api.config.get_settings", lambda: settings(**values))
    with pytest.raises(providers.AIProviderError):
        providers.create_provider(provider_name="bedrock", model="deepseek.v3.2")


@pytest.mark.parametrize("profile", ["default", "deep_research"])
def test_every_public_profile_uses_the_primary_bedrock_model(profile):
    primary = BedrockProvider(model="deepseek.v3.2", api_key="synthetic-test-key")
    chosen = pipeline.answer_provider(settings(), AIAnswerRequest(question="Hukuki soru"), primary, profile=profile)
    assert chosen is not primary
    assert isinstance(chosen, BedrockProvider)
    assert chosen.model == primary.model
    assert not isinstance(chosen, FallbackProvider)


@pytest.mark.parametrize("scope", ["case_id", "project_id", "selected_document_ids"])
def test_private_scope_keeps_bedrock_primary_but_not_public_scope(scope):
    from uuid import uuid4
    value = [uuid4()] if scope == "selected_document_ids" else uuid4()
    request = AIAnswerRequest(question="Belgeyi açıkla", **{scope: value})
    primary = BedrockProvider(model="deepseek.v3.2", api_key="synthetic-test-key")
    assert pipeline.answer_provider(settings(), request, primary) is primary
    assert not pipeline.cloud_allowed(request)  # no public web/cache permission


def test_secondary_planner_is_disabled_in_single_provider_mode():
    assert pipeline._planner(settings(cloud_ai_plan_model="another-model")) is None


def test_scoped_bedrock_does_not_take_local_gpu_lock():
    import asyncio

    async def check():
        primary = BedrockProvider(model="deepseek.v3.2", api_key="synthetic-test-key")
        assert pipeline._generation_slot(primary, primary) is not pipeline._generation_lock

    asyncio.run(check())


def test_bedrock_failure_never_falls_back_to_ollama(monkeypatch):
    import httpx

    monkeypatch.setattr(providers, "OllamaProvider", Mock(side_effect=AssertionError("local model")))
    primary = BedrockProvider(
        model="deepseek.v3.2", api_key="synthetic-test-key", busy_waits=(),
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={"message": "Unavailable"})),
    )
    with pytest.raises(providers.AIProviderError):
        primary.generate(system_instruction="Synthetic instruction", prompt="Synthetic text")


def test_private_office_generation_uses_the_bedrock_primary(monkeypatch):
    import asyncio
    from api import office_ai

    configured = settings(
        ai_model="deepseek.v3.2", ollama_base_url="http://127.0.0.1:1",
        ollama_timeout_seconds=20, ollama_max_output_tokens=100,
        ollama_num_ctx=2048, ollama_keep_alive="0",
    )
    calls = []
    monkeypatch.setattr("api.config.get_settings", lambda: configured)
    monkeypatch.setattr(office_ai, "get_settings", lambda: configured)
    monkeypatch.setattr(providers, "OllamaProvider", Mock(side_effect=AssertionError("local model")))

    def generate(self, *, system_instruction, prompt):
        calls.append((self.name, self.model))
        return "Synthetic summary"

    monkeypatch.setattr(BedrockProvider, "generate", generate)
    result = asyncio.run(office_ai._generate("Synthetic instruction", "Synthetic document"))
    assert result == ("Synthetic summary", "deepseek.v3.2")
    assert calls == [("bedrock", "deepseek.v3.2")]
