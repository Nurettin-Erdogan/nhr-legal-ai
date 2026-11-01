"""Backfill semantic vectors for legal corpus or private document chunks."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import sleep
from typing import Any, Callable
from uuid import UUID

import psycopg
from psycopg import sql

from api.ai.embeddings import EmbeddingProvider, EmbeddingProviderError, vector_literal
from api.embed_pause import wait_if_embeddings_paused

logger = logging.getLogger(__name__)

ZERO_UUID = UUID("00000000-0000-0000-0000-000000000000")


@dataclass(frozen=True, slots=True)
class EmbeddingSummary:
    embedded: int
    remaining: int
    last_id: Any = None


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
            "bağlanılamadı",
            "yanıt süresini aştı",
            "timed out",
            "timeout",
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
        wait_if_embeddings_paused()
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
            wait_if_embeddings_paused()
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
    count_remaining: bool = True,
    after_id: Any = None,
    shard_index: int = 0,
    shard_count: int = 1,
    jobs: int = 1,
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
        count_remaining=count_remaining,
        after_id=after_id,
        shard_index=shard_index,
        shard_count=shard_count,
        jobs=jobs,
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
    count_remaining: bool = True,
    after_id: Any = None,
    shard_index: int = 0,
    shard_count: int = 1,
    jobs: int = 1,
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
        count_remaining=count_remaining,
        after_id=after_id,
        shard_index=shard_index,
        shard_count=shard_count,
        jobs=jobs,
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
    count_remaining: bool = True,
    after_id: Any = None,
    shard_index: int = 0,
    shard_count: int = 1,
    jobs: int = 1,
) -> EmbeddingSummary:
    if table_name not in {"legal_chunks", "document_chunks"}:
        raise ValueError("Desteklenmeyen embedding tablosu")
    table = sql.Identifier(table_name)
    shards = max(1, int(shard_count))
    shard = int(shard_index) % shards
    workers = max(1, int(jobs))
    wait_if_embeddings_paused()
    rows = connection.execute(
        sql.SQL(
            "SELECT id, content FROM {} "
            "WHERE (embedding IS NULL OR embedding_model IS DISTINCT FROM %(model)s) "
            "AND id > %(after_id)s "
            "AND mod(abs(hashtext(id::text)), %(shards)s) = %(shard)s "
            "ORDER BY id LIMIT %(limit)s"
        ).format(table),
        {
            "model": provider.model,
            "after_id": after_id or ZERO_UUID,
            "shards": shards,
            "shard": shard,
            "limit": limit,
        },
    ).fetchall()
    embedded = 0
    last_id = rows[-1][0] if rows else after_id
    batches = [rows[offset : offset + batch_size] for offset in range(0, len(rows), batch_size)]
    update_sql = sql.SQL(
        "UPDATE {} SET embedding = %s::vector, embedding_model = %s, "
        "embedding_created_at = NOW() WHERE id = %s"
    ).format(table)

    def _vectors_for(batch: list) -> list[list[float]]:
        wait_if_embeddings_paused()
        vectors = _embed_batch_with_retry(
            provider,
            [row[1] for row in batch],
            max_retries=max(0, max_retries),
            retry_backoff_seconds=retry_backoff_seconds,
        )
        if len(vectors) != len(batch):
            raise RuntimeError("Embedding sayısı kaynak parça sayısıyla eşleşmiyor")
        return vectors

    def _write(batch: list, vectors: list[list[float]]) -> int:
        params = []
        for row, vector in zip(batch, vectors, strict=True):
            if len(vector) != provider.dimensions:
                raise RuntimeError("Embedding boyutu yapılandırmayla eşleşmiyor")
            params.append((vector_literal(vector), provider.model, row[0]))
        with connection.transaction(), connection.cursor() as cursor:
            cursor.executemany(update_sql, params)
        return len(params)

    if workers == 1:
        for index, batch in enumerate(batches):
            written = _write(batch, _vectors_for(batch))
            embedded += written
            logger.info("Embedding ilerlemesi: %s/%s", embedded, len(rows))
            if delay_seconds > 0 and index + 1 < len(batches):
                sleep(delay_seconds)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(_vectors_for, batch): batch for batch in batches}
            for future in as_completed(pending):
                batch = pending[future]
                written = _write(batch, future.result())
                embedded += written
                logger.info("Embedding ilerlemesi: %s/%s", embedded, len(rows))

    if not count_remaining:
        remaining = 0 if embedded == 0 else 1
        return EmbeddingSummary(embedded=embedded, remaining=remaining, last_id=last_id)

    remaining_row = connection.execute(
        sql.SQL(
            "SELECT EXISTS ("
            "SELECT 1 FROM {} "
            "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s "
            "LIMIT 1)"
        ).format(table),
        (provider.model,),
    ).fetchone()
    remaining = int(bool(remaining_row and remaining_row[0]))
    return EmbeddingSummary(embedded=embedded, remaining=remaining, last_id=last_id)
