"""Araştırmaya özel Pro profili: ağ/ücret/DB olmadan yönlendirme ve kaynak kapısı."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from api import config, deep_research, office_ai
from api.ai import pipeline
from api.ai.cache import answer_cache
from api.ai.cloud_provider import DeepSeekCloudProvider
from api.ai.cloud_provider import FallbackProvider
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context
from tests.test_ai_pipeline import _settings


def settings(**overrides):
    values = dict(
        cloud_ai_provider="deepseek", cloud_ai_model="deepseek-flash", cloud_ai_api_key="test-only",
        cloud_ai_timeout_seconds=90, cloud_ai_max_output_tokens=4096, cloud_ai_reasoning_effort="low",
        deep_research_cloud_enabled=True, deep_research_ai_model="deepseek-v4-pro",
        deep_research_ai_api_key="test-only", deep_research_ai_max_output_tokens=16384,
        deep_research_ai_timeout_seconds=180, deep_research_ai_reasoning_effort="max",
    )
    values.update(overrides)
    return _settings(**values)


def test_research_pro_max_is_independent_of_general_flash():
    local = SimpleNamespace(name="qwen", model="local")
    request = AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?")
    general = pipeline.answer_provider(settings(), request, local)
    research = pipeline.answer_provider(settings(), request, local, profile="deep_research")
    assert general.primary.model == "deepseek-flash" and general.primary.reasoning_effort == "low"
    assert general.primary.max_output_tokens == 4096
    assert research.primary.model == "deepseek-v4-pro" and research.primary.reasoning_effort == "max"
    assert research.primary.max_output_tokens == 16384 and research.primary.timeout_seconds == 180
    assert pipeline.provider_cache_model(general, "default") != pipeline.provider_cache_model(research, "deep_research")
    # Aynı model seçilse bile profil/düşünme seviyesi ayrı önbellektir.
    same_model = pipeline.answer_provider(settings(cloud_ai_model="deepseek-v4-pro"), request, local)
    assert pipeline.provider_cache_model(same_model, "default") != pipeline.provider_cache_model(research, "deep_research")


@pytest.mark.parametrize("overrides", [
    {"deep_research_cloud_enabled": False}, {"deep_research_ai_api_key": ""},
    {"deep_research_ai_reasoning_effort": "invalid"},
])
def test_unconfigured_research_is_local_not_silently_flash(overrides):
    local = SimpleNamespace(name="qwen", model="local")
    assert pipeline.answer_provider(settings(**overrides), AIAnswerRequest(question="Genel hukuk sorusu"),
                                    local, profile="deep_research") is local


@pytest.mark.parametrize("scope", [
    {"case_id": uuid4()}, {"project_id": uuid4()}, {"office_project_id": uuid4()},
    {"selected_document_ids": [uuid4()]},
])
def test_pro_profile_cannot_override_private_scope(scope, monkeypatch):
    def forbidden(**_):
        pytest.fail("Özel kapsam için bulut sağlayıcısı oluşturulmamalı")

    monkeypatch.setattr(pipeline, "create_cloud_provider", forbidden)
    local = SimpleNamespace(name="qwen", model="local")
    assert pipeline.answer_provider(settings(), AIAnswerRequest(question="Dosyadaki süreyi incele", **scope),
                                    local, profile="deep_research") is local


def test_research_config_is_opt_in_bounded_and_secret_is_hidden(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setattr(config, "dotenv_values", lambda _: {})
    monkeypatch.setenv("DATABASE_URL", "postgresql://test-only")
    monkeypatch.setenv("CLOUD_AI_PROVIDER", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "not-real-secret")
    for key in ("DEEP_RESEARCH_CLOUD_ENABLED", "DEEP_RESEARCH_AI_MODEL", "DEEP_RESEARCH_AI_REASONING_EFFORT",
                "DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS", "DEEP_RESEARCH_AI_TIMEOUT_SECONDS",
                "DEEP_RESEARCH_AI_PROVIDER", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    config.get_settings.cache_clear()
    try:
        result = config.get_settings()
        assert not result.deep_research_cloud_enabled
        assert result.deep_research_ai_model == "deepseek-v4-pro"
        assert result.deep_research_ai_reasoning_effort == "max"
        assert result.deep_research_ai_api_key == "not-real-secret" and result.cloud_ai_api_key == ""
        assert result.deep_research_ai_max_output_tokens == 0
        assert result.deep_research_ai_timeout_seconds == 180
        assert "not-real-secret" not in repr(result)
        monkeypatch.setenv("DEEP_RESEARCH_CLOUD_ENABLED", "true")
        monkeypatch.setenv("DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS", "999999")
        monkeypatch.setenv("DEEP_RESEARCH_AI_TIMEOUT_SECONDS", "999999")
        config.get_settings.cache_clear()
        result = config.get_settings()
        assert result.deep_research_cloud_enabled
        assert result.deep_research_ai_max_output_tokens == 393216
        assert result.deep_research_ai_timeout_seconds == 300
    finally:
        config.get_settings.cache_clear()


def test_client_request_cannot_select_paid_research_profile():
    assert "generation_profile" not in AIAnswerRequest.model_fields
    assert "generation_profile" not in office_ai.DeepResearchRequest.model_fields


def test_only_research_helpers_disable_thinking_without_mutating_main_pro():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Yanıt"}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

    cloud = DeepSeekCloudProvider(model="deepseek-v4-pro", api_key="test-only", reasoning_effort="max",
        max_output_tokens=16384, timeout_seconds=180, transport=httpx.MockTransport(handler))
    local = SimpleNamespace(name="qwen", model="local")
    provider = FallbackProvider(primary=cloud, fallback=local)
    helper = pipeline.auxiliary_provider(provider, "deep_research")
    assert helper.generate(system_instruction="Yalnız JSON döndür", prompt="p") == "Yanıt"
    assert provider.generate(system_instruction="s", prompt="p") == "Yanıt"
    assert [b["model"] for b in seen] == ["deepseek-v4-pro"] * 2
    assert [b["reasoning_effort"] for b in seen] == ["none", "max"]
    assert [b["thinking"] for b in seen] == [{"type": "disabled"}, {"type": "enabled"}]
    assert [b["max_tokens"] for b in seen] == [16384, 16384]
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert cloud.reasoning_effort == "max" and cloud.timeout_seconds == 180 and cloud.max_output_tokens == 16384
    assert cloud.last_usage.eval_count == 20 and not provider.fell_back
    assert pipeline.auxiliary_provider(local, "default") is local


def test_general_flash_helpers_preserve_output_policy_without_changing_primary_low_profile():
    cloud = DeepSeekCloudProvider(model="deepseek-flash", api_key="test-only", reasoning_effort="low",
        max_output_tokens=4096)
    provider = FallbackProvider(primary=cloud, fallback=SimpleNamespace(name="qwen", model="local"))
    helper = pipeline.auxiliary_provider(provider, "default")
    assert helper is not provider and helper.base is provider
    assert cloud.reasoning_effort == "low" and cloud.max_output_tokens == 4096
    assert "aux-none-uncapped-v2" in pipeline.provider_cache_model(provider, "default")


def test_helper_failure_preserves_sticky_fallback_and_usage():
    cloud = DeepSeekCloudProvider(model="deepseek-v4-pro", api_key="test-only", reasoning_effort="max",
        transport=httpx.MockTransport(lambda _: httpx.Response(402)))
    local = SimpleNamespace(name="qwen", model="local", generate=lambda **_: "Yerel")
    provider = FallbackProvider(primary=cloud, fallback=local)
    assert pipeline.auxiliary_provider(provider, "deep_research").generate(system_instruction="s", prompt="p") == "Yerel"
    assert provider.fell_back and provider.model == "local"
    assert provider.generate(system_instruction="s", prompt="p") == "Yerel"


def install_pipeline(monkeypatch, *, remote_status=200, unsafe=False):
    calls = []
    context = court_decision_context()
    correct = "İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır. [K1]"

    def handler(request):
        calls.append(json.loads(request.content))
        if remote_status != 200:
            return httpx.Response(remote_status)
        text = "Uydurulan karar gereğince tazminat her durumda 999 kat ödenir. [K99]" if unsafe else correct
        return httpx.Response(200, json={"choices": [{"message": {
            "content": text, "reasoning_content": "PRIVATE_REASONING_NOT_FOR_REPORT",
        }, "finish_reason": "stop"}]})

    class Local:
        name = "qwen"
        model = "local-qwen"

        def generate(self, **_):
            return correct

    def cloud(**kwargs):
        return DeepSeekCloudProvider(model=kwargs["model"], api_key=kwargs["api_key"],
            reasoning_effort=kwargs["reasoning_effort"], max_output_tokens=kwargs["max_output_tokens"],
            timeout_seconds=kwargs["timeout_seconds"], transport=httpx.MockTransport(handler))

    async def history(*_):
        return [], []

    monkeypatch.setattr(pipeline, "get_settings", settings)
    monkeypatch.setattr(pipeline, "create_provider", lambda **_: Local())
    monkeypatch.setattr(pipeline, "create_cloud_provider", cloud)
    monkeypatch.setattr(pipeline, "_retrieve", lambda *_, **__: [context])
    monkeypatch.setattr(pipeline, "_load_history", history)
    monkeypatch.setattr(pipeline, "persist_answer", lambda *_, **__: (uuid4(), uuid4()))
    monkeypatch.setattr(pipeline, "generate_grounded_answer",
                        lambda provider, **_: provider.generate(system_instruction="s", prompt="p"))
    return calls


@pytest.mark.parametrize("remote_status, expected_model", [(200, "deepseek-v4-pro"), (402, "local-qwen")])
def test_actual_research_runner_uses_pro_or_records_local_fallback(monkeypatch, remote_status, expected_model):
    calls = install_pipeline(monkeypatch, remote_status=remote_status)

    async def hints(_):
        return []

    monkeypatch.setattr(office_ai, "_statute_hints_async", hints)
    monkeypatch.setattr(office_ai, "_save_deep_research", lambda _: uuid4())
    job = deep_research.ResearchJob(id=uuid4(), owner_id=uuid4(), question="Kıdem tazminatı şartları nelerdir?")
    answer_cache.clear()
    try:
        asyncio.run(office_ai._deep_run(job))
        assert job.state == "done" and job.saved_id and len(job.steps) == 3
        assert all(step.model == expected_model and not step.error for step in job.steps)
        assert any(step.grounded for step in job.steps)
        assert len(calls) == 3
        assert all(body["model"] == "deepseek-v4-pro" and body["reasoning_effort"] == "max"
                   and body["thinking"] == {"type": "enabled"} and body["max_tokens"] == 16384 for body in calls)
        assert "PRIVATE_REASONING" not in json.dumps(job.as_dict())
        assert {step["model"] for step in job.as_dict()["steps"]} == {expected_model}
    finally:
        answer_cache.clear()


def test_pro_answer_does_not_bypass_citation_verifier(monkeypatch):
    calls = install_pipeline(monkeypatch, unsafe=True)
    answer_cache.clear()
    try:
        with pytest.raises(HTTPException) as error:
            asyncio.run(pipeline.execute_answer(AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"),
                                               None, generation_profile="deep_research"))
        assert error.value.status_code == 422
        assert len(calls) == 1
        assert len(answer_cache) == 0
    finally:
        answer_cache.clear()


def test_private_source_in_research_context_is_never_sent_to_pro(monkeypatch):
    calls = install_pipeline(monkeypatch)
    private = replace(court_decision_context(), source_type="document", verification="user_document")
    monkeypatch.setattr(pipeline, "_retrieve", lambda *_, **__: [private])
    answer_cache.clear()
    try:
        result, _ = asyncio.run(pipeline.execute_answer(
            AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"), None,
            generation_profile="deep_research",
        ))
        assert result.model == "local-qwen" and result.grounded
        assert calls == []
    finally:
        answer_cache.clear()


def test_risk_analysis_keeps_default_profile(monkeypatch):
    seen = []

    async def execute(request, user_id, **kwargs):
        seen.append(kwargs["generation_profile"])
        return SimpleNamespace(answer="Kaynak bulunamadı.", grounded=False, citations=[], conversation_id=None), None

    monkeypatch.setattr(pipeline, "execute_answer", execute)
    asyncio.run(office_ai._risk("Kıdem tazminatı şartları nelerdir?", uuid4()))
    assert seen == ["default"] * 3
