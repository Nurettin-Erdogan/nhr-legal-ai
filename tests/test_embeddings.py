from __future__ import annotations

import pytest

from api.ai.embeddings import (
    EmbeddingProviderError,
    create_embedding_provider,
    vector_literal,
)
from ingestion.embeddings import _embed_batch_with_retry


def test_vector_literal_uses_pgvector_text_format():
    assert vector_literal([0.5, -1, 0.125]) == "[0.5,-1,0.125]"


def test_vector_literal_rejects_empty_vectors():
    with pytest.raises(ValueError, match="boş"):
        vector_literal([])


def test_vector_literal_rejects_non_finite_values():
    with pytest.raises(ValueError, match="sonlu"):
        vector_literal([float("nan")])


def test_provider_requires_api_key():
    with pytest.raises(EmbeddingProviderError, match="API_KEY"):
        create_embedding_provider(
            provider_name="gemini",
            api_key=None,
            model="gemini-embedding-2",
            dimensions=768,
        )


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
            raise EmbeddingProviderError("invalid API key")

    with pytest.raises(EmbeddingProviderError, match="invalid API key"):
        _embed_batch_with_retry(
            PermanentProvider(),
            ["metin"],
            max_retries=3,
            retry_backoff_seconds=1,
            sleeper=lambda _: pytest.fail("kalıcı hata beklememeli"),
        )
