"""Karar metnini RAG için deterministik parçalara böler."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1800

_PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    content: str
    paragraph_start: int
    paragraph_end: int
    content_hash: str


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _split_oversized(paragraph: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    remaining = paragraph

    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        split_at = window.rfind(" ")
        if split_at <= 0:
            split_at = max_chars
        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        pieces.append(remaining)

    return pieces


def chunk_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    """Paragraf sınırlarını koruyarak `max_chars` sınırına kadar parça üretir."""
    if max_chars <= 0:
        raise ValueError("max_chars pozitif olmalıdır.")

    paragraphs = [part.strip() for part in _PARAGRAPH_SEPARATOR.split(text)]
    paragraphs = [part for part in paragraphs if part]

    chunks: list[TextChunk] = []
    buffer: list[str] = []
    buffer_start = 0

    def flush(paragraph_end: int) -> None:
        if not buffer:
            return
        content = "\n\n".join(buffer)
        chunks.append(
            TextChunk(
                index=len(chunks),
                content=content,
                paragraph_start=buffer_start,
                paragraph_end=paragraph_end,
                content_hash=_hash(content),
            )
        )
        buffer.clear()

    for position, paragraph in enumerate(paragraphs):
        if len(paragraph) > max_chars:
            flush(position - 1 if position > buffer_start else buffer_start)
            for piece in _split_oversized(paragraph, max_chars):
                chunks.append(
                    TextChunk(
                        index=len(chunks),
                        content=piece,
                        paragraph_start=position,
                        paragraph_end=position,
                        content_hash=_hash(piece),
                    )
                )
            buffer_start = position + 1
            continue

        candidate_length = sum(len(item) + 2 for item in buffer) + len(paragraph)
        if buffer and candidate_length > max_chars:
            flush(position - 1)
            buffer_start = position

        if not buffer:
            buffer_start = position
        buffer.append(paragraph)

    flush(len(paragraphs) - 1)

    return chunks
