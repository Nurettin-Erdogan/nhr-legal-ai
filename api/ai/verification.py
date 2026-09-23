from __future__ import annotations

import re
from dataclasses import dataclass

from api.ai.rag import RAGContext, uncited_claims

_MARKER_PATTERN = re.compile(r"\[\s*K\s*(\d+)\s*\]", re.IGNORECASE)
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([.,;:!?])")
_REPEATED_SPACE = re.compile(r"[ \t]{2,}")
_FOREIGN_SCRIPT_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_INSUFFICIENT_SOURCE_RE = re.compile(
    r"(kaynak(larda|lar)?\s+((bu konuda\s+)?yeterli bilgi|yetersiz)"
    r"|yeterli kaynak (yok|bulunamadı)"
    r"|atıf (yapılamıyor|yapamadım))",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class VerifiedAnswer:
    text: str
    contexts: tuple[RAGContext, ...]
    unverified_markers: tuple[str, ...]
    unsupported_claims: tuple[str, ...] = ()
    foreign_script_detected: bool = False

    @property
    def grounded(self) -> bool:
        return (
            bool(self.contexts)
            and not self.unsupported_claims
            and not self.foreign_script_detected
        )


def verify_answer(answer: str, contexts: list[RAGContext]) -> VerifiedAnswer:
    """Keep only the citation markers backed by a retrieved source.

    The prompt tells the model to cite what it used, but nothing stops it from
    inventing a marker or citing a source it never received. Markers outside the
    retrieved range are stripped from the text so a reader never sees a reference
    that resolves to nothing, and the returned contexts are limited to the
    sources the answer actually leans on rather than everything retrieval found.
    """
    cited: list[int] = []
    unverified: list[str] = []
    for raw_index in _MARKER_PATTERN.findall(answer):
        index = int(raw_index)
        if 1 <= index <= len(contexts):
            if index not in cited:
                cited.append(index)
        elif f"K{raw_index}" not in unverified:
            unverified.append(f"K{raw_index}")

    positions = {original: position for position, original in enumerate(cited, start=1)}

    def renumber(match: re.Match[str]) -> str:
        position = positions.get(int(match.group(1)))
        return f"[K{position}]" if position else ""

    text = _MARKER_PATTERN.sub(renumber, answer)
    if unverified:
        text = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
        text = _REPEATED_SPACE.sub(" ", text)

    cited_contexts = tuple(contexts[index - 1] for index in cited)
    return VerifiedAnswer(
        text=text.strip(),
        contexts=cited_contexts,
        unverified_markers=tuple(unverified),
        unsupported_claims=uncited_claims(text, len(cited_contexts)),
        foreign_script_detected=bool(_FOREIGN_SCRIPT_RE.search(text)),
    )


def is_insufficient_source_reply(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact or len(compact) > 280:
        return False
    if _MARKER_PATTERN.search(compact):
        return False
    return bool(_INSUFFICIENT_SOURCE_RE.search(compact))
