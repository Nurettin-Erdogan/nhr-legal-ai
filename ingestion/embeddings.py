"""Backfill semantic vectors for legal corpus or private document chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import sleep
from typing import Callable

import psycopg
from psycopg import sql

from api.ai.embeddings import EmbeddingProvider, EmbeddingProviderError, vector_literal

logger = logging.getLogger(__name__)

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
    return _embed_chunks(
        connection,
        provider,
        table_name="legal_chunks",
        limit=limit,
        batch_size=batch_size,
        delay_seconds=delay_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def embed_document_chunks(
    connection: psycopg.Connection,
    provider: EmbeddingProvider,
    *,
    limit: int = 500,
    batch_size: int = 10,
    delay_seconds: float = 0,
    max_retries: int = 0,
    retry_backoff_seconds: float = 15,
) -> EmbeddingSummary:
    """Embed private documents only when explicitly requested by an operator."""
    return _embed_chunks(
        connection,
        provider,
        table_name="document_chunks",
        limit=limit,
        batch_size=batch_size,
        delay_seconds=delay_seconds,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def _embed_chunks(
    connection: psycopg.Connection,
    provider: EmbeddingProvider,
    *,
    table_name: str,
    limit: int,
    batch_size: int,
    delay_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> EmbeddingSummary:
    if table_name not in {"legal_chunks", "document_chunks"}:
        raise ValueError("Desteklenmeyen embedding tablosu")
    table = sql.Identifier(table_name)
    rows = connection.execute(
        sql.SQL(
            "SELECT id, content FROM {} "
            "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %(model)s "
            "ORDER BY created_at, id LIMIT %(limit)s"
        ).format(table),
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
                    sql.SQL(
                        "UPDATE {} SET embedding = %s::vector, embedding_model = %s, "
                        "embedding_created_at = NOW() WHERE id = %s"
                    ).format(table),
                    (vector_literal(vector), provider.model, row[0]),
                )
                embedded += 1
        logger.info("Embedding ilerlemesi: %s/%s", embedded, len(rows))
        if delay_seconds > 0 and offset + batch_size < len(rows):
            sleep(delay_seconds)

    remaining = connection.execute(
        sql.SQL(
            "SELECT count(*) FROM {} "
            "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s"
        ).format(table),
        (provider.model,),
    ).fetchone()[0]
    return EmbeddingSummary(embedded=embedded, remaining=remaining)
