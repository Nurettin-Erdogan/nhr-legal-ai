from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from api.ai.providers import (
    AIProviderError,
    OllamaProvider,
    create_provider,
)
from api.ai import routes
from api.ai.rag import generate_grounded_answer
from api.ai.verification import verify_answer
from tests.factories import court_decision_context


def test_provider_selection_uses_deepseek_without_api_key():
    deepseek = create_provider(provider_name="deepseek", model="deepseek-r1:8b")

    assert isinstance(deepseek, OllamaProvider)
    assert deepseek.name == "deepseek"


def test_gemini_is_no_longer_a_supported_provider():
    with pytest.raises(AIProviderError, match="Desteklenmeyen"):
        create_provider(provider_name="gemini", model="gemini-test")


def test_qwen_is_no_longer_a_supported_provider():
    with pytest.raises(AIProviderError, match="Desteklenmeyen"):
        create_provider(provider_name="qwen", model="qwen3:8b")


def test_deepseek_uses_existing_rag_prompt_and_citation_verification():
    context = court_decision_context()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-r1:8b"
        assert body["stream"] is False
        assert body["think"] is False
        assert body["options"]["num_predict"] == 512
        assert "olmayan bir kaynağa atıf yapma" in body["messages"][0]["content"]
        assert context.content in body["messages"][1]["content"]
        assert "[K1]" in body["messages"][1]["content"]
        return httpx.Response(200, json={"message": {"content": "Sonuç. [K1] Yanlış. [K9]"}})

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        name="deepseek",
        transport=httpx.MockTransport(respond),
    )
    raw = generate_grounded_answer(provider, question="Haklı fesih?", contexts=[context])
    answer = verify_answer(raw, [context])

    assert answer.text == "Sonuç. [K1] Yanlış."
    assert answer.contexts == (context,)
    assert answer.unverified_markers == ("K9",)


def test_ollama_status_checks_local_model():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "deepseek-r1:8b"}]})

    provider = OllamaProvider(model="deepseek-r1:8b", transport=httpx.MockTransport(respond))
    assert provider.is_available()
    provider.model = "deepseek-r1:1.5b"
    assert not provider.is_available()


def test_ollama_missing_model_has_safe_error():
    provider = OllamaProvider(
        model="deepseek-r1:8b",
        transport=httpx.MockTransport(lambda request: httpx.Response(404, text="private-data")),
    )
    with pytest.raises(AIProviderError) as error:
        provider.generate(system_instruction="rules", prompt="question")

    assert error.value.status_code == 503
    assert "ollama pull deepseek-r1:8b" in str(error.value)
    assert "private-data" not in str(error.value)


def test_ollama_rejects_invalid_base_url():
    with pytest.raises(AIProviderError):
        OllamaProvider(model="deepseek-r1:8b", base_url="http://localhost:11434/unexpected/path")


def test_question_embedding_uses_supported_provider_arguments(monkeypatch):
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        embedding_dimensions=768,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=180.0,
    ))

    class StubEmbeddingProvider:
        def embed_query(self, question: str) -> list[float]:
            assert question == "Hukuki soru?"
            return [0.5]

    def create_stub_embedding_provider(
        *, provider_name, model, dimensions, ollama_base_url,
        ollama_timeout_seconds,
    ):
        assert provider_name
        assert model
        assert dimensions > 0
        assert ollama_timeout_seconds > 0
        return StubEmbeddingProvider()

    monkeypatch.setattr(routes, "create_embedding_provider", create_stub_embedding_provider)
    assert asyncio.run(routes._embed_question("Hukuki soru?")) == [0.5]
