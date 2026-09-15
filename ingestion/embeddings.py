"""Backfill semantic vectors for legal corpus chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import sleep
from typing import Callable

import psycopg

from api.ai.embeddings import EmbeddingProvider, EmbeddingProviderError, vector_literal

logger = logging.getLogger(__name__)

_SELECT_PENDING = """
SELECT id, content
FROM legal_chunks
WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %(model)s
ORDER BY created_at, id
LIMIT %(limit)s
"""

_UPDATE_CHUNK = """
UPDATE legal_chunks
SET embedding = %s::vector,
    embedding_model = %s,
    embedding_created_at = NOW()
WHERE id = %s
"""


@dataclass(frozen=True, slots=True)
class EmbeddingSummary:
    embedded: int
    remaining: int


def _is_transient_embedding_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    messages: list[str] = []
    while current is not None:
        messages.append(str(current).lower())
        code = getattr(current, "code", None)
        if code in {429, 500, 502, 503, 504}:
            return True
        current = current.__cause__
    message = " ".join(messages)
    return any(
        marker in message
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "resource_exhausted",
            "high demand",
            "unavailable",
        )
    )


def _embed_batch_with_retry(
    provider: EmbeddingProvider,
    texts: list[str],
    *,
    max_retries: int,
    retry_backoff_seconds: float,
    sleeper: Callable[[float], None] = sleep,
) -> list[list[float]]:
    for attempt in range(max_retries + 1):
        try:
            return provider.embed_documents(texts)
        except EmbeddingProviderError as exc:
            if attempt >= max_retries or not _is_transient_embedding_error(exc):
                raise
            wait = max(0.0, retry_backoff_seconds) * (2**attempt)
            logger.warning(
                "Embedding kotası/servisi geçici olarak kullanılamıyor; "
                "%.1f saniye sonra yeniden denenecek (%s/%s)",
                wait,
                attempt + 2,
                max_retries + 1,
            )
            sleeper(wait)
    raise AssertionError("unreachable")


def embed_legal_chunks(
    connection: psycopg.Connection,
    provider: EmbeddingProvider,
    *,
    limit: int = 500,
    batch_size: int = 10,
    delay_seconds: float = 0,
    max_retries: int = 0,
    retry_backoff_seconds: float = 15,
) -> EmbeddingSummary:
    rows = connection.execute(
        _SELECT_PENDING,
        {"model": provider.model, "limit": limit},
    ).fetchall()
    embedded = 0

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        vectors = _embed_batch_with_retry(
            provider,
            [row[1] for row in batch],
            max_retries=max(0, max_retries),
            retry_backoff_seconds=retry_backoff_seconds,
        )
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding sayısı kaynak parça sayısıyla eşleşmiyor")

        with connection.transaction(), connection.cursor() as cursor:
            for row, vector in zip(batch, vectors, strict=True):
                if len(vector) != provider.dimensions:
                    raise RuntimeError("Embedding boyutu yapılandırmayla eşleşmiyor")
                cursor.execute(
                    _UPDATE_CHUNK,
                    (vector_literal(vector), provider.model, row[0]),
                )
                embedded += 1
        logger.info("Embedding ilerlemesi: %s/%s", embedded, len(rows))
        if delay_seconds > 0 and offset + batch_size < len(rows):
            sleep(delay_seconds)

    remaining = connection.execute(
        "SELECT count(*) FROM legal_chunks "
        "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s",
        (provider.model,),
    ).fetchone()[0]
    return EmbeddingSummary(embedded=embedded, remaining=remaining)
