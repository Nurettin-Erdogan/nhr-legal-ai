"""Bulut modeli (2026-10-19): yalnız genel soruda, maskeli, hata verirse yerel modelle; dava belgesi hiç gitmez."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from api.ai import pipeline
from api.ai.cloud_provider import (
    AnthropicProvider,
    DeepSeekCloudProvider,
    FallbackProvider,
    OpenAIProvider,
    create_cloud_provider,
    mask_personal_data,
)
from api.ai.providers import AIProviderError
from api.schemas import AIAnswerRequest


def _transport(handler):
    return httpx.MockTransport(handler)


def test_anthropic_request_shape_and_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Hayır, artış 12 aylık ortalamayı geçemez."}],
                                         "stop_reason": "end_turn", "usage": {"input_tokens": 900, "output_tokens": 40}})

    provider = AnthropicProvider(model="claude-haiku-5-5", api_key="test-key", transport=_transport(handler))
    text = provider.generate(system_instruction="Kaynaklara dayan.", prompt="Soru")
    assert text.startswith("Hayır")
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "test-key" and seen["headers"]["anthropic-version"]
    assert seen["body"]["system"] == "Kaynaklara dayan."
    # Current Claude API: no sampling parameters (400 since 2026-10-21); depth via output_config.effort.
    assert "temperature" not in seen["body"] and seen["body"]["output_config"] == {"effort": "low"}
    assert seen["body"]["messages"] == [{"role": "user", "content": "Soru"}]
    assert provider.last_usage.prompt_eval_count == 900 and provider.last_usage.eval_count == 40
    assert "test-key" not in repr(provider)


def test_openai_request_shape_json_mode_and_answer():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"results":[true]}'}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    provider = OpenAIProvider(model="gpt-5-mini", api_key="k", transport=_transport(handler))
    assert provider.generate(system_instruction="Yalnız JSON döndür.", prompt="x") == '{"results":[true]}'
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "Yalnız JSON döndür."}


def test_deepseek_uses_its_own_openai_compatible_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hayır."}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 800, "completion_tokens": 20}})

    provider = create_cloud_provider(provider_name="deepseek", model="", api_key="k")
    assert isinstance(provider, DeepSeekCloudProvider) and provider.model == "deepseek-flash"
    provider.transport = _transport(handler)
    assert provider.generate(system_instruction="s", prompt="Kiracı 12345678901") == "Hayır."
    assert seen["url"] == "https://api.deepseek.com/v1/chat/completions"
    assert "max_tokens" not in seen["body"] and "max_completion_tokens" not in seen["body"]
    assert seen["body"]["reasoning_effort"] == "low"
    assert seen["body"]["thinking"] == {"type": "enabled"}
    assert "temperature" not in seen["body"]
    assert "12345678901" not in json.dumps(seen["body"], ensure_ascii=False)


def test_a_rejected_setting_is_dropped_and_retried_once():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature'"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "tamam"}, "finish_reason": "stop"}]})

    provider = OpenAIProvider(model="gpt-4.1-mini", api_key="k", transport=_transport(handler))
    assert provider.generate(system_instruction="s", prompt="p") == "tamam"
    assert len(bodies) == 2 and "temperature" not in bodies[1]


@pytest.mark.parametrize("status,needle", [(401, "anahtar"), (402, "bakiyesi"), (429, "sınırı"), (500, "yanıt veremiyor")])
def test_errors_are_explained_in_turkish(status, needle):
    provider = AnthropicProvider(model="m", api_key="k", transport=_transport(lambda request: httpx.Response(status)))
    with pytest.raises(AIProviderError, match=needle):
        provider.generate(system_instruction="s", prompt="p")


def test_a_cut_answer_keeps_the_partial_text():
    def handler(request):
        return httpx.Response(200, json={"content": [{"type": "text", "text": "- bir\n- iki"}], "stop_reason": "max_tokens"})

    with pytest.raises(AIProviderError) as info:
        AnthropicProvider(model="m", api_key="k", transport=_transport(handler)).generate(system_instruction="s", prompt="p")
    assert info.value.partial == "- bir\n- iki"


def test_personal_identifiers_are_masked_but_legal_numbers_are_not():
    text = ("Müvekkil 12345678901 TC, tel 0532 123 45 67, a.b@ornek.com, IBAN TR12 0006 1005 1978 6457 8413 26. "
            "TBK m. 344, 6098 sayılı Kanun, E. 2019/769 K. 2021/394, 01.04.2021, 20/2/1930 tarihli 1567 sayılı.")
    masked = mask_personal_data(text)
    for secret in ("12345678901", "0532 123 45 67", "a.b@ornek.com", "TR12 0006"):
        assert secret not in masked
    for kept in ("TBK m. 344", "6098 sayılı", "E. 2019/769 K. 2021/394", "01.04.2021", "20/2/1930", "1567 sayılı"):
        assert kept in masked


def test_the_prompt_is_masked_before_it_leaves():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})

    AnthropicProvider(model="m", api_key="k", transport=_transport(handler)).generate(
        system_instruction="s", prompt="Kiracı 12345678901 kimlik numaralı")
    assert "12345678901" not in json.dumps(seen["body"], ensure_ascii=False)


class _Fake:
    def __init__(self, name, result=None, error=None):
        self.name, self.model, self.result, self.error, self.calls = name, f"{name}-model", result, error, 0
        self.last_usage = None

    def generate(self, *, system_instruction, prompt):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_fallback_uses_the_local_model_when_the_cloud_fails_but_not_for_a_cut_answer():
    local = _Fake("qwen", result="yerel")
    provider = FallbackProvider(primary=_Fake("anthropic", error=AIProviderError("kota")), fallback=local)
    assert provider.generate(system_instruction="s", prompt="p") == "yerel" and provider.fell_back
    assert provider.name == "qwen" and provider.model == "qwen-model"
    assert provider.generate(system_instruction="s", prompt="ikinci çağrı") == "yerel"
    assert provider.primary.calls == 1 and local.calls == 2

    cut = FallbackProvider(primary=_Fake("anthropic", error=AIProviderError("kesildi", partial="- a")), fallback=local)
    with pytest.raises(AIProviderError):
        cut.generate(system_instruction="s", prompt="p")
    assert local.calls == 2


def test_no_key_means_no_cloud_provider():
    with pytest.raises(AIProviderError, match="anahtar"):
        create_cloud_provider(provider_name="anthropic", model="m", api_key="")


def test_cloud_pauses_embeddings_only_during_real_local_fallback(monkeypatch):
    from contextlib import contextmanager
    from api import embed_pause
    events = []

    @contextmanager
    def guard():
        events.append('pause')
        try:
            yield
        finally:
            events.append('resume')

    monkeypatch.setattr(embed_pause, 'local_generation_pause', guard)
    local = _Fake('qwen', result='local')
    success = FallbackProvider(primary=_Fake('openrouter', result='cloud'), fallback=local)
    assert success.generate(system_instruction='s', prompt='p') == 'cloud'
    assert events == []
    failed = FallbackProvider(primary=_Fake('openrouter', error=AIProviderError('offline')), fallback=local)
    assert failed.generate(system_instruction='s', prompt='p') == 'local'
    assert events == ['pause', 'resume']


def _settings(**overrides):
    values = dict(cloud_ai_provider="anthropic", cloud_ai_model="claude-haiku-5-5", cloud_ai_api_key="k",
                  cloud_ai_timeout_seconds=30.0, cloud_ai_max_output_tokens=1024)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_luna_user_effort_is_request_local_and_cache_separated(effort):
    settings = _settings(cloud_ai_provider="openrouter", cloud_ai_model="openai/gpt-6-luna",
                         cloud_ai_reasoning_effort="low")
    local = _Fake("qwen")
    provider = pipeline.answer_provider(settings, AIAnswerRequest(question="Soru", reasoning_effort=effort), local)
    assert isinstance(provider, FallbackProvider)
    assert provider.primary._generation_options()["reasoning"] == {"effort": effort}
    assert f":{effort}:" in pipeline.provider_cache_model(provider, "default")
    assert settings.cloud_ai_reasoning_effort == "low"
    private = AIAnswerRequest(question="Özel belge", project_id=uuid4(), reasoning_effort=effort)
    assert pipeline.answer_provider(settings, private, local) is local


def test_user_effort_rejects_unknown_values():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AIAnswerRequest(question="Soru", reasoning_effort="unlimited")


def test_luna_effort_missing_preserves_configured_default():
    provider = pipeline.answer_provider(
        _settings(cloud_ai_provider="openrouter", cloud_ai_model="openai/gpt-6-luna",
                  cloud_ai_reasoning_effort="high"), AIAnswerRequest(question="Soru"), _Fake("qwen"))
    assert provider.primary.reasoning_effort == "high"


@pytest.mark.parametrize("scope", [{"case_id": uuid4()}, {"project_id": uuid4()}, {"office_project_id": uuid4()},
                                   {"selected_document_ids": [uuid4()]}])
def test_case_or_document_questions_always_stay_local(scope):
    local = _Fake("qwen")
    request = AIAnswerRequest(question="Bu dosyada süre ne zaman doluyor?", **scope)
    assert pipeline.answer_provider(_settings(), request, local) is local


def test_a_general_question_goes_to_the_cloud_only_when_configured():
    local = _Fake("qwen")
    request = AIAnswerRequest(question="Kira artışı TÜFE'yi geçebilir mi?")
    assert pipeline.answer_provider(_settings(cloud_ai_provider=""), request, local) is local
    assert pipeline.answer_provider(_settings(cloud_ai_api_key=""), request, local) is local
    routed = pipeline.answer_provider(_settings(), request, local)
    assert isinstance(routed, FallbackProvider) and routed.fallback is local


def test_private_documents_in_the_sources_force_the_local_model():
    official = SimpleNamespace(verification="official", source_type="legislation")
    document = SimpleNamespace(verification="user_document", source_type="document")
    assert not pipeline.holds_private_documents([official])
    assert pipeline.holds_private_documents([official, document])


def test_claude_gets_a_real_max_tokens_and_a_refusal_falls_back_to_local():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [], "stop_reason": "refusal"})

    provider = create_cloud_provider(provider_name="anthropic", model="", api_key="k", max_output_tokens=0,
                                     reasoning_effort="medium")
    provider.transport = _transport(handler)
    with pytest.raises(AIProviderError) as info:
        provider.generate(system_instruction="s", prompt="p")
    assert not info.value.partial  # not a cut answer: FallbackProvider may continue on the local model
    assert seen["body"]["model"] == "claude-haiku-5-5" and seen["body"]["max_tokens"] == 16000
    assert seen["body"]["output_config"] == {"effort": "medium"}


def test_openrouter_serves_the_deepseek_models_with_its_own_reasoning_field():
    """2026-10-23: a Turkish card could not top up DeepSeek; the same models through OpenRouter."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Hayır."}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    provider = create_cloud_provider(provider_name="openrouter", model="", api_key="or-key", reasoning_effort="low")
    provider.transport = _transport(handler)
    assert provider.generate(system_instruction="s", prompt="Kiracı 12345678901") == "Hayır."
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions" and seen["auth"] == "Bearer or-key"
    assert seen["body"]["model"] == "deepseek/deepseek-v4-flash"
    assert seen["body"]["reasoning"] == {"effort": "low"} and "thinking" not in seen["body"]
    assert seen["body"]["provider"] == {"order": ["Azure", "Parasail", "DeepInfra"]}
    assert "12345678901" not in json.dumps(seen["body"], ensure_ascii=False)
    helper = {}
    provider.transport = _transport(lambda request: helper.update(json.loads(request.content)) or httpx.Response(
        200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}))
    provider.generate_auxiliary(system_instruction="s", prompt="p")
    assert helper["reasoning"] == {"enabled": False}  # helper checks run without thinking, as on DeepSeek


def test_openrouter_does_not_force_json_mode():
    """Azure on OpenRouter returned empty content with response_format=json_object (2026-10-24)."""
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a":1}'}, "finish_reason": "stop"}]})

    provider = create_cloud_provider(provider_name="openrouter", model="", api_key="k")
    provider.transport = _transport(handler)
    provider.generate(system_instruction="Yalnız JSON döndür.", prompt="p")
    assert "response_format" not in seen["body"]


def test_openrouter_openai_checker_uses_a_strict_schema_without_forcing_approval():
    from api.ai.synthesis import CHECK_INSTRUCTION
    from api.ai.checker_protocol import verdict_status
    seen = {}
    verdict = json.dumps({'claims': [{'id': 1, 'supported': False, 'relevant': True,
        'scope_preserved': False, 'why': 'ifade_duzelt: fixture'}],
        'coverage_preserved': False, 'source_only': True, 'clarification_safe': True})
    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': verdict}, 'finish_reason': 'stop'}]})
    provider = create_cloud_provider(provider_name='openrouter', model='openai/gpt-6-luna', api_key='fixture')
    provider.transport = _transport(handler)
    raw = provider.generate_auxiliary(system_instruction=CHECK_INSTRUCTION, prompt='{}')
    assert verdict_status(raw, 1) == 'valid'
    response_format = seen['response_format']
    assert response_format['type'] == 'json_schema' and response_format['json_schema']['strict'] is True
    schema = response_format['json_schema']['schema']
    assert schema['additionalProperties'] is False
    assert schema['properties']['claims']['items']['properties']['supported'] == {'type': 'boolean'}
    assert seen['provider']['require_parameters'] is True
    assert seen['reasoning'] == {'enabled': False}


def test_openrouter_openai_plan_is_json_but_normal_answer_remains_plain_text():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]})
    provider = create_cloud_provider(provider_name='openrouter', model='openai/gpt-6-luna', api_key='fixture')
    provider.transport = _transport(handler)
    provider.generate(system_instruction='Yalnız JSON döndür.', prompt='{}')
    provider.generate(system_instruction='Kaynaklarla doğal Türkçe cevapla.', prompt='{}')
    assert seen[0]['response_format'] == {'type': 'json_object'}
    assert 'response_format' not in seen[1]


def test_one_empty_cloud_response_is_retried_before_falling_back_to_the_local_model():
    from api.ai.cloud_provider import FallbackProvider
    from api.ai.providers import AIProviderError

    class Cloud:
        name, model = "cloud", "m"

        def __init__(self, *outcomes):
            self.outcomes, self.calls = list(outcomes), 0

        def generate(self, **kwargs):
            self.calls += 1
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class Local:
        name, model = "local", "q"
        calls = 0

        def generate(self, **kwargs):
            Local.calls += 1
            return "yerel"

    empty = AIProviderError("openrouter boş bir yanıt döndürdü")
    retried = FallbackProvider(Cloud(empty, "bulut"), Local())
    assert retried.generate(system_instruction="s", prompt="p") == "bulut" and not retried.fell_back and Local.calls == 0
    failing = FallbackProvider(Cloud(empty, empty), Local())
    assert failing.generate(system_instruction="s", prompt="p") == "yerel" and failing.fell_back
    other = Cloud(AIProviderError("ağ hatası"))
    assert FallbackProvider(other, Local()).generate(system_instruction="s", prompt="p") == "yerel" and other.calls == 1


def test_gemini_uses_googles_openai_compatible_endpoint_and_masks_identifiers(monkeypatch):
    from api.ai.cloud_provider import GeminiProvider, create_cloud_provider

    sent = {}

    def fake_post(self, url, headers, payload):
        sent.update(url=url, payload=payload, auth=headers["authorization"])
        return {"choices": [{"message": {"content": "tamam"}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(GeminiProvider, "_post", fake_post)
    provider = create_cloud_provider(provider_name="gemini", model="", api_key="k")
    assert provider.generate(system_instruction="talimat", prompt="TC 12345678901 olan kişi") == "tamam"
    assert sent["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert sent["payload"]["model"] == "gemini-3.8-flash" and "max_tokens" not in sent["payload"]
    assert "12345678901" not in sent["payload"]["messages"][1]["content"]


def test_gemini_waits_and_retries_when_google_is_busy_but_not_on_a_bad_key(monkeypatch):
    import httpx

    from api.ai import cloud_provider
    from api.ai.cloud_provider import GeminiProvider, create_cloud_provider

    monkeypatch.setattr(cloud_provider.time, "sleep", lambda _s: None)
    replies = []

    def fake_post(self, url, headers, payload):
        status = replies.pop(0)
        if status != 200:
            response = httpx.Response(status, request=httpx.Request("POST", url))
            raise cloud_provider._error_for("Gemini", httpx.HTTPStatusError("x", request=response.request, response=response)) \
                from httpx.HTTPStatusError("x", request=response.request, response=response)
        return {"choices": [{"message": {"content": "tamam"}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(GeminiProvider, "_post", fake_post)
    provider = create_cloud_provider(provider_name="gemini", model="", api_key="k")
    replies[:] = [503, 503, 200]
    assert provider.generate(system_instruction="s", prompt="p") == "tamam"
    replies[:] = [401, 200]
    import pytest

    with pytest.raises(cloud_provider.AIProviderError):
        provider.generate(system_instruction="s", prompt="p")
def test_openrouter_public_plans_use_bounded_strict_shapes_without_answer_limits():
    from api.ai.free_answer import PLAN_INSTRUCTION as QUESTION_PLAN
    from api.ai.research_plan import PLAN_INSTRUCTION as RESEARCH_PLAN
    provider = create_cloud_provider(provider_name='openrouter', model='openai/gpt-6-luna', api_key='fixture')
    before = provider.max_output_tokens
    for instruction, field, maximum in [(QUESTION_PLAN, 'parts', 4), (RESEARCH_PLAN, 'aspects', 5)]:
        result = provider._json_response_format(instruction)
        assert result['type'] == 'json_schema'
        schema = result['json_schema']['schema']
        assert result['json_schema']['strict'] is True
        assert schema['additionalProperties'] is False
        assert schema['properties'][field]['maxItems'] == maximum
        assert schema['properties'][field]['items']['additionalProperties'] is False
    assert provider.max_output_tokens == before


def test_bedrock_uses_the_converse_endpoint_with_a_bearer_key_and_ignores_reasoning_blocks(monkeypatch):
    from api.ai import cloud_provider
    from api.ai.cloud_provider import BedrockProvider, create_cloud_provider

    sent = {}

    def fake_post(self, url, headers, payload):
        sent.update(url=url, auth=headers["authorization"], payload=payload)
        return {"output": {"message": {"content": [{"reasoningContent": {"reasoningText": {"text": "gizli"}}},
                                                   {"text": "tamam"}]}},
                "stopReason": "end_turn", "usage": {"inputTokens": 7, "outputTokens": 2}}

    monkeypatch.setattr(BedrockProvider, "_post", fake_post)
    provider = create_cloud_provider(provider_name="bedrock", model="", api_key="k")
    assert provider.generate(system_instruction="talimat", prompt="TC 12345678901 olan kişi") == "tamam"
    assert sent["url"] == "https://bedrock-runtime.eu-north-1.amazonaws.com/model/openai.gpt-6-luna/converse"
    assert sent["auth"] == "Bearer k" and "12345678901" not in json.dumps(sent["payload"])
    assert provider.last_usage.prompt_eval_count == 7 and "gizli" not in "tamam"


def test_bedrock_refuses_a_truncated_answer(monkeypatch):
    import pytest

    from api.ai.cloud_provider import AIProviderError, BedrockProvider, create_cloud_provider

    monkeypatch.setattr(BedrockProvider, "_post", lambda *a: {"output": {"message": {"content": [{"text": "yarım"}]}},
                                                              "stopReason": "max_tokens", "usage": {}})
    with pytest.raises(AIProviderError):
        create_cloud_provider(provider_name="bedrock", model="", api_key="k").generate(system_instruction="s", prompt="p")
