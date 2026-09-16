from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from api.ai.providers import (
    AIProviderError,
    OllamaProvider,
    create_provider,
)
from api.ai import routes
from api.ai.rag import generate_grounded_answer
from api.ai.verification import verify_answer
from api.schemas import AIAnswerRequest
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
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-r1:8b"
        assert body["stream"] is False
        assert body["raw"] is True
        assert body["keep_alive"] == "30m"
        assert body["options"]["num_predict"] == 384
        assert body["options"]["num_ctx"] == 1536
        assert body["options"]["stop"] == [
            "<｜end▁of▁sentence｜>", "<｜User｜>", "<｜Assistant｜>"
        ]
        assert body["prompt"].startswith("<｜begin▁of▁sentence｜>")
        assert "<｜User｜>" in body["prompt"]
        assert "<｜Assistant｜>" in body["prompt"]
        assert "<think>\n</think>" in body["prompt"]
        assert "olmayan bir kaynağa atıf yapma" in body["prompt"]
        assert context.content in body["prompt"]
        assert "[K1]" in body["prompt"]
        return httpx.Response(200, json={"response": "Sonuç. [K1] Yanlış. [K9]"})

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


def test_ollama_strips_think_blocks_from_answer():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": "<think>gizli</think>\nSonuç. [K1]"},
        )

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        transport=httpx.MockTransport(respond),
    )
    assert provider.generate(system_instruction="rules", prompt="question") == "Sonuç. [K1]"


def test_ollama_rejects_truncated_answer():
    provider = OllamaProvider(
        model="deepseek-r1:8b",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"response": "Yarım cümle [K1]", "done_reason": "length"},
            )
        ),
    )
    with pytest.raises(AIProviderError, match="token sınırında kesildi"):
        provider.generate(system_instruction="rules", prompt="question")


def test_answer_route_rejects_uncited_legal_response(monkeypatch):
    context = court_decision_context()
    settings = SimpleNamespace(
        ai_provider="deepseek",
        ai_model="deepseek-r1:8b",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=120.0,
        ollama_max_output_tokens=384,
        ollama_num_ctx=1536,
        ollama_keep_alive="30m",
        rag_query_embedding=False,
        rag_top_k=2,
        embedding_model="nomic-embed-text",
        rag_context_chars=800,
    )

    @contextmanager
    def database_stub():
        yield object()

    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    monkeypatch.setattr(routes, "create_provider", lambda **kwargs: SimpleNamespace(
        name="deepseek", model="deepseek-r1:8b"
    ))
    monkeypatch.setattr(routes, "database_connection", database_stub)
    monkeypatch.setattr(routes, "retrieve_contexts", lambda *args, **kwargs: [context])
    monkeypatch.setattr(
        routes, "generate_grounded_answer", lambda *args, **kwargs: "Kaynaksız hukuki sonuç."
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.answer_question(AIAnswerRequest(question="Haklı fesih?"), None))

    assert error.value.status_code == 422
