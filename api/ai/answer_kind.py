"""Server-owned answer modes; absence in older history remains fail-closed."""

from typing import Literal

AnswerKind = Literal["legal", "conversation", "clarification", "insufficient_sources", "general_information"]


def stored_answer_kind(value: object) -> AnswerKind:
    if value in ("conversation", "clarification", "insufficient_sources", "general_information"):
        return value
    return "legal"
