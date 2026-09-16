from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol
from urllib.parse import urlsplit

import httpx


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


@dataclass(slots=True)
class QwenEmbeddingProvider:
    model: str = "qwen3-embedding:0.6b"
    dimensions: int = 768
    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 120.0
    name: str = "qwen"
    transport: httpx.BaseTransport | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise EmbeddingProviderError("OLLAMA_BASE_URL geçerli bir sunucu adresi olmalı")
        if self.dimensions <= 0:
            raise EmbeddingProviderError("Embedding boyutu pozitif olmalı")

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout_seconds,
            transport=self.transport,
            trust_env=False,
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        cleaned = [text.strip() for text in texts]
        if any(not text for text in cleaned):
            raise EmbeddingProviderError("Boş metin için embedding üretilemez")
        try:
            with self._client() as client:
                response = client.post(
                    "/api/embed",
                    json={
                        "model": self.model,
                        "input": cleaned,
                        "dimensions": self.dimensions,
                        "truncate": True,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError("Ollama embedding yanıt süresini aştı") from exc
        except httpx.ConnectError as exc:
            raise EmbeddingProviderError("Ollama embedding sunucusuna bağlanılamadı") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise EmbeddingProviderError(
                    f"Ollama embedding modeli bulunamadı: {self.model}. "
                    f"Önce ollama pull {self.model} çalıştırın."
                ) from exc
            raise EmbeddingProviderError(
                f"Ollama embedding isteği başarısız: HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise EmbeddingProviderError("Ollama embedding yanıtı okunamadı") from exc

        raw_vectors = payload.get("embeddings")
        if not isinstance(raw_vectors, list) or len(raw_vectors) != len(cleaned):
            raise EmbeddingProviderError("Ollama beklenen sayıda embedding döndürmedi")
        vectors: list[list[float]] = []
        for raw_vector in raw_vectors:
            if not isinstance(raw_vector, list):
                raise EmbeddingProviderError("Ollama geçersiz embedding döndürdü")
            vector = [float(value) for value in raw_vector]
            if len(vector) != self.dimensions:
                raise EmbeddingProviderError(
                    f"Ollama embedding boyutu beklenenden farklı: {len(vector)} != {self.dimensions}"
                )
            if not all(isfinite(value) for value in vector):
                raise EmbeddingProviderError("Ollama sonlu olmayan embedding değeri döndürdü")
            vectors.append(vector)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)


def create_embedding_provider(
    *,
    provider_name: str,
    api_key: str | None,
    model: str,
    dimensions: int,
    ollama_base_url: str = "http://127.0.0.1:11434",
    ollama_timeout_seconds: float = 120.0,
) -> EmbeddingProvider:
    normalized = provider_name.strip().lower()
    if normalized == "qwen":
        return QwenEmbeddingProvider(
            model=model,
            dimensions=dimensions,
            base_url=ollama_base_url,
            timeout_seconds=ollama_timeout_seconds,
        )
    if normalized == "gemini":
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
