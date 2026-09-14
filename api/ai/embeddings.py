from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    """An embedding provider could not produce usable vectors."""


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(slots=True)
class GeminiEmbeddingProvider:
    api_key: str
    model: str = "gemini-embedding-2"
    dimensions: int = 768
    name: str = "gemini"

    def _embed(self, texts: list[str], *, task: str) -> list[list[float]]:
        if not texts:
            return []

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            contents = [
                types.Content(
                    parts=[
                        types.Part.from_text(
                            text=f"task: {task} | text: {text.strip()}"
                        )
                    ]
                )
                for text in texts
            ]
            response = client.models.embed_content(
                model=self.model,
                contents=contents,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.dimensions,
                ),
            )
        except Exception as exc:
            raise EmbeddingProviderError(f"Gemini embedding isteği başarısız: {exc}") from exc

        vectors = [list(item.values or []) for item in response.embeddings or []]
        if len(vectors) != len(texts) or any(
            len(vector) != self.dimensions for vector in vectors
        ):
            raise EmbeddingProviderError("Embedding servisi beklenen boyutta vektör döndürmedi")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], task="retrieval_query")[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, task="retrieval_document")


def create_embedding_provider(
    *,
    provider_name: str,
    api_key: str | None,
    model: str,
    dimensions: int,
) -> EmbeddingProvider:
    if provider_name == "gemini":
        if not api_key:
            raise EmbeddingProviderError(
                "EMBEDDING_API_KEY veya GEMINI_API_KEY tanımlı değil"
            )
        return GeminiEmbeddingProvider(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
        )
    raise EmbeddingProviderError(f"Desteklenmeyen embedding sağlayıcısı: {provider_name}")


def vector_literal(vector: list[float]) -> str:
    """Serialize a validated numeric vector for pgvector's text input format."""
    if not vector:
        raise ValueError("Embedding vektörü boş olamaz")
    values = [float(value) for value in vector]
    if not all(isfinite(value) for value in values):
        raise ValueError("Embedding vektörü sonlu sayılardan oluşmalıdır")
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"
