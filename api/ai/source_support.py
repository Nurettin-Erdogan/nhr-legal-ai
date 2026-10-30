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
_END = re.compile(r'[.!?](?:[0-9]{1,3})?["”»]?(?=\s|$)')
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


_FIELD_LINE = re.compile(r"^[^\s:][^:]{0,40}:\s*\S")


def _document_units(text: str) -> list[str]:
    """Kullanıcı belgesinin kanıt birimleri: cümleler ve "Etiket: değer" satırları.

    Hukuk metni akan cümlelerden oluşur; kullanıcı belgesinde ise bilginin çoğu satır yapısındadır ("Tarih: 10.04.2025",
    "Muhatap: Mehmet Kaya"). Bütün boşlukları tek satıra indiren `_sentences`, bu satırları başlıkla birlikte tek dev
    "cümle"ye katıyor, nokta ile bitmeyen son satırı da hiç vermiyordu (ölçüldü: 2026-10-06). Burada paragraf sınırı
    (boş satır) her zaman birim sınırıdır; paragraf içinde başlık (tümü büyük harf) ve "Etiket: değer" satırları yeni birim
    başlatır, diğer satırlar bir öncekine eklenir (PDF'lerde cümle satır sonunda bölünür). Belge parçaları paragraf
    sınırında kesildiği için son birim de tamdır ve atılmaz.
    """
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        current: list[str] = []

        def flush() -> None:
            if current:
                units.extend(_sentences(" ".join(current)))
                current.clear()

        for line in (part.strip() for part in paragraph.split("\n")):
            if not line:
                continue
            heading = line == line.upper() and any(char.isalpha() for char in line) and len(line.split()) <= 8
            if heading:
                flush()
                units.append(" ".join(line.split()))
            elif _FIELD_LINE.match(line):
                flush()
                current.append(line)
            else:
                current.append(line)
        flush()
    return units


def source_sentences(context: RAGContext) -> list[str]:
    """Bir kaynağın, cevaba aynen alınabilecek tam birimleri (kanıt seçimi ve destek denetimi aynı listeyi kullanır)."""
    if context.source_type == "document":
        return _document_units(context.content)
    return _sentences(context.content, include_tail=False)


def unsupported_source_claims(text: str, contexts: Sequence[RAGContext]) -> tuple[str, ...]:
    evidence = [{_normalize(s) for s in source_sentences(c)} for c in contexts]
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
