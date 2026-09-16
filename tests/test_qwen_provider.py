from __future__ import annotations

import json

import httpx
import pytest

from api.ai.providers import AIProviderError, GeminiProvider, QwenProvider, create_provider
from api.ai.rag import generate_grounded_answer
from api.ai.verification import verify_answer
from tests.factories import court_decision_context


def test_provider_selection_preserves_gemini_and_needs_no_key_for_qwen():
    gemini = create_provider(provider_name="gemini", api_key="test", model="gemini-test")
    qwen = create_provider(provider_name="qwen", api_key=None, model="qwen3:8b")

    assert isinstance(gemini, GeminiProvider)
    assert isinstance(qwen, QwenProvider)
    assert qwen.name == "qwen"


def test_qwen_uses_existing_rag_prompt_and_citation_verification():
    context = court_decision_context()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "qwen3:8b"
        assert body["stream"] is False
        assert body["think"] is False
        assert "olmayan bir kaynağa atıf yapma" in body["messages"][0]["content"]
        assert context.content in body["messages"][1]["content"]
        assert "[K1]" in body["messages"][1]["content"]
        return httpx.Response(200, json={"message": {"content": "Sonuç. [K1] Yanlış. [K9]"}})

    provider = QwenProvider(model="qwen3:8b", transport=httpx.MockTransport(respond))
    raw = generate_grounded_answer(provider, question="Haklı fesih?", contexts=[context])
    answer = verify_answer(raw, [context])

    assert answer.text == "Sonuç. [K1] Yanlış."
    assert answer.contexts == (context,)
    assert answer.unverified_markers == ("K9",)


def test_qwen_status_checks_local_model():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    provider = QwenProvider(model="qwen3:8b", transport=httpx.MockTransport(respond))
    assert provider.is_available()
    provider.model = "qwen3:4b"
    assert not provider.is_available()


def test_qwen_missing_model_has_safe_error():
    provider = QwenProvider(
        model="qwen3:8b",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, text="private-data")),
    )
    with pytest.raises(AIProviderError) as error:
        provider.generate(system_instruction="rules", prompt="question")

    assert error.value.status_code == 503
    assert "ollama pull qwen3:8b" in str(error.value)
    assert "private-data" not in str(error.value)


def test_qwen_rejects_invalid_base_url():
    with pytest.raises(AIProviderError):
        QwenProvider(model="qwen3:8b", base_url="http://localhost:11434/unexpected/path")
