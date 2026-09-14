"""Backfill semantic vectors for legal corpus chunks."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg

from api.ai.embeddings import EmbeddingProvider, vector_literal

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


def embed_legal_chunks(
    connection: psycopg.Connection,
    provider: EmbeddingProvider,
    *,
    limit: int = 500,
    batch_size: int = 10,
) -> EmbeddingSummary:
    rows = connection.execute(
        _SELECT_PENDING,
        {"model": provider.model, "limit": limit},
    ).fetchall()
    embedded = 0

    for offset in range(0, len(rows), batch_size):
        batch = rows[offset : offset + batch_size]
        vectors = provider.embed_documents([row[1] for row in batch])
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

    remaining = connection.execute(
        "SELECT count(*) FROM legal_chunks "
        "WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s",
        (provider.model,),
    ).fetchone()[0]
    return EmbeddingSummary(embedded=embedded, remaining=remaining)
