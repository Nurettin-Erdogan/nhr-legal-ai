from __future__ import annotations

import json

import httpx
import pytest

from api.ai.embeddings import (
    EmbeddingProviderError,
    QwenEmbeddingProvider,
    create_embedding_provider,
    vector_literal,
)
from ingestion.cli import build_parser
from ingestion.embeddings import _embed_batch_with_retry, _embed_chunks


def test_vector_literal_uses_pgvector_text_format():
    assert vector_literal([0.5, -1, 0.125]) == "[0.5,-1,0.125]"


def test_vector_literal_rejects_empty_vectors():
    with pytest.raises(ValueError, match="boş"):
        vector_literal([])


def test_vector_literal_rejects_non_finite_values():
    with pytest.raises(ValueError, match="sonlu"):
        vector_literal([float("nan")])


def test_qwen_embedding_provider_needs_no_api_key():
    provider = create_embedding_provider(
        provider_name="qwen",
        api_key=None,
        model="qwen3-embedding:0.6b",
        dimensions=3,
    )
    assert isinstance(provider, QwenEmbeddingProvider)
    assert provider.name == "qwen"


def test_qwen_embedding_calls_ollama_embed_with_configured_dimensions():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        body = json.loads(request.content)
        assert body == {
            "model": "qwen3-embedding:0.6b",
            "input": ["hukuk", "karar"],
            "dimensions": 3,
            "truncate": True,
        }
        return httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]},
        )

    provider = QwenEmbeddingProvider(
        model="qwen3-embedding:0.6b",
        dimensions=3,
        transport=httpx.MockTransport(respond),
    )
    assert provider.embed_documents(["hukuk", "karar"]) == [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]


def test_qwen_embedding_missing_model_has_safe_error():
    provider = QwenEmbeddingProvider(
        model="qwen3-embedding:0.6b",
        dimensions=3,
        transport=httpx.MockTransport(lambda request: httpx.Response(404, text="private")),
    )
    with pytest.raises(EmbeddingProviderError, match="ollama pull qwen3-embedding:0.6b"):
        provider.embed_query("hukuk")


class _TransientProvider:
    name = "fake"
    model = "fake-model"
    dimensions = 2

    def __init__(self) -> None:
        self.calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == 1:
            raise EmbeddingProviderError("429 RESOURCE_EXHAUSTED")
        return [[0.1, 0.2] for _ in texts]


def test_embedding_batch_retries_transient_quota_error():
    provider = _TransientProvider()
    waits: list[float] = []

    vectors = _embed_batch_with_retry(
        provider,
        ["metin"],
        max_retries=2,
        retry_backoff_seconds=3,
        sleeper=waits.append,
    )

    assert vectors == [[0.1, 0.2]]
    assert provider.calls == 2
    assert waits == [3]


def test_embedding_batch_does_not_retry_permanent_error():
    class PermanentProvider(_TransientProvider):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            raise EmbeddingProviderError("invalid model")

    with pytest.raises(EmbeddingProviderError, match="invalid model"):
        _embed_batch_with_retry(
            PermanentProvider(),
            ["metin"],
            max_retries=3,
            retry_backoff_seconds=1,
            sleeper=lambda _: pytest.fail("kalıcı hata beklememeli"),
        )


def test_embedding_cli_keeps_private_documents_opt_in():
    parser = build_parser()

    assert parser.parse_args(["embed"]).target == "legal"
    assert parser.parse_args(["embed", "--target", "documents"]).target == "documents"


def test_embedding_cli_defaults_to_qwen_without_provider_env(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)

    args = build_parser().parse_args(["embed"])

    assert args.provider == "qwen"
    assert args.model == "qwen3-embedding:0.6b"
    assert args.dimensions == 768


def test_embedding_table_name_is_strictly_allowlisted():
    with pytest.raises(ValueError, match="Desteklenmeyen"):
        _embed_chunks(
            None,
            _TransientProvider(),
            table_name="users",
            limit=1,
            batch_size=1,
            delay_seconds=0,
            max_retries=0,
            retry_backoff_seconds=0,
        )
