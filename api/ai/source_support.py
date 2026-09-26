"""Conservative extractive support gate, not a semantic/legal truth classifier.

Until a paraphrase evaluator is calibrated, accept only complete source sentences.
Whitespace and surrounding quotation marks may differ; words, conditions, numbers
and polarity may not. Metadata is never treated as evidence for a legal claim.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from api.ai.rag import RAGContext

_MARKER = re.compile(r"\[\s*K\s*(\d+)\s*\]", re.IGNORECASE)
_AFTER_SENTENCE = re.compile(r'([.!?]["”»]?)[ \t]*((?:\[\s*K\s*\d+\s*\][ \t]*)+)', re.IGNORECASE)
_END = re.compile(r'[.!?]["”»]?(?=\s|$)')
_ABBREVIATIONS = {"mad", "no", "prof", "dr", "av", "bkz", "vb", "vs", "ltd", "md"}


def _normalize(text: str) -> str:
    text = " ".join(unicodedata.normalize("NFC", text).split())
    text = re.sub(r"\s+([.!?,;:])", r"\1", text)
    for opening, closing in (("“", "”"), ('"', '"'), ("«", "»")):
        if text.startswith(opening) and text.endswith(closing):
            return text[1:-1].strip()
    return text


def _sentences(text: str, *, include_tail: bool = True) -> list[str]:
    """Use conservative boundaries: never split a decimal, initial or abbreviation."""
    text = " ".join(text.split())
    pieces: list[str] = []
    start = 0
    for match in _END.finditer(text):
        if match.group().startswith("."):
            before = _MARKER.sub("", text[start:match.start()]).rstrip()
            word_match = re.search(r"(\w+)$", before)
            word = word_match.group() if word_match else ""
            if not word or word.isdigit() or len(word) <= 2 or word.casefold() in _ABBREVIATIONS:
                continue
        pieces.append(text[start:match.end()].strip())
        start = match.end()
    if include_tail and text[start:].strip():
        pieces.append(text[start:].strip())
    return pieces


def unsupported_source_claims(text: str, contexts: Sequence[RAGContext]) -> tuple[str, ...]:
    evidence = [{_normalize(s) for s in _sentences(c.content, include_tail=False)} for c in contexts]
    normalized = _AFTER_SENTENCE.sub(lambda m: f" {m.group(2).strip()}{m.group(1)} ", text)
    unsupported: list[str] = []
    for line in normalized.splitlines():
        for sentence in _sentences(line):
            markers = [int(value) for value in _MARKER.findall(sentence)]
            claim = _normalize(_MARKER.sub("", sentence))
            if not any(character.isalnum() for character in claim):
                unsupported.append(sentence)
                continue
            # Every attached citation must actually contain the full claim.
            if not markers or any(
                index < 1 or index > len(evidence) or claim not in evidence[index - 1]
                for index in markers
            ):
                unsupported.append(sentence)
    return tuple(unsupported)
