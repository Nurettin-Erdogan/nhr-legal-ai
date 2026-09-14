from __future__ import annotations

import pytest

from api.ai.embeddings import (
    EmbeddingProviderError,
    create_embedding_provider,
    vector_literal,
)


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
