from __future__ import annotations

import asyncio
import json
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
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-r1:8b"
        assert body["stream"] is False
        assert body["raw"] is True
        assert body["keep_alive"] == "30m"
        assert body["options"]["num_predict"] == 768
        assert body["options"]["num_ctx"] == 3072
        assert body.get("think") is False
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
        response = "Sonuç. [K1] Yanlış. [K9]"
        return httpx.Response(200, json={"response": response})

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        name="deepseek",
        transport=httpx.MockTransport(respond),
    )
    raw = generate_grounded_answer(provider, question="Haklı fesih?", contexts=[context])
    answer = verify_answer(raw, [context])

    assert calls == 1
    assert answer.text == "Sonuç. [K1] Yanlış."
    assert answer.contexts == (context,)
    assert answer.unverified_markers == ("K9",)
    assert not answer.grounded


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
    from api.ai import pipeline as ai_pipeline

    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: SimpleNamespace(
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

    monkeypatch.setattr(ai_pipeline, "create_embedding_provider", create_stub_embedding_provider)
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


def test_ollama_records_token_usage_on_success():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": "Sonuç. [K1]",
                "done_reason": "stop",
                "prompt_eval_count": 120,
                "eval_count": 40,
            },
        )

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        transport=httpx.MockTransport(respond),
    )
    assert provider.generate(system_instruction="rules", prompt="question") == "Sonuç. [K1]"
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_eval_count == 120
    assert provider.last_usage.eval_count == 40
    assert provider.last_usage.done_reason == "stop"


def test_num_predict_keeps_768_at_3072_ctx_for_typical_prompt():
    captured: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content)["options"])
        return httpx.Response(
            200,
            json={"response": "Sonuç. [K1]", "done_reason": "stop"},
        )

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        max_output_tokens=768,
        num_ctx=3072,
        transport=httpx.MockTransport(respond),
    )
    provider.generate(system_instruction="A" * 800, prompt="B" * 3200)
    assert captured["num_ctx"] == 3072
    assert captured["num_predict"] == 768


def test_num_predict_is_capped_to_fit_num_ctx():
    captured: dict[str, object] = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content)["options"])
        return httpx.Response(200, json={"response": "Sonuç. [K1]"})

    provider = OllamaProvider(
        model="deepseek-r1:8b",
        max_output_tokens=768,
        num_ctx=1536,
        transport=httpx.MockTransport(respond),
    )
    provider.generate(system_instruction="A" * 2500, prompt="B" * 2500)
    assert captured["num_ctx"] == 1536
    assert captured["num_predict"] < 768
    assert captured["num_predict"] >= 64


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
    from api.ai import pipeline as ai_pipeline
    from api.ai.cache import answer_cache

    context = court_decision_context()
    settings = SimpleNamespace(
        ai_provider="deepseek",
        ai_model="deepseek-r1:8b",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_seconds=120.0,
        ollama_max_output_tokens=768,
        ollama_num_ctx=3072,
        ollama_keep_alive="30m",
        rag_query_embedding=False,
        rag_top_k=2,
        embedding_model="nomic-embed-text",
        rag_context_chars=800,
    )
    answer_cache.clear()
    monkeypatch.setattr(ai_pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(ai_pipeline, "create_provider", lambda **kwargs: SimpleNamespace(
        name="deepseek", model="deepseek-r1:8b"
    ))
    monkeypatch.setattr(ai_pipeline, "_retrieve", lambda *args, **kwargs: [context])
    monkeypatch.setattr(
        ai_pipeline, "generate_grounded_answer", lambda *args, **kwargs: "Kaynaksız hukuki sonuç."
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.answer_question(AIAnswerRequest(question="Haklı fesih?"), None))

    assert error.value.status_code == 422
