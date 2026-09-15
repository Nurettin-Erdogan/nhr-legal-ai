from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from api.ai.rag import RAGContext
from api.ai.verification import VerifiedAnswer

_TITLE_LENGTH = 80
_SNIPPET_LENGTH = 500


def _conversation_title(question: str) -> str:
    condensed = " ".join(question.split())
    if len(condensed) <= _TITLE_LENGTH:
        return condensed
    return condensed[: _TITLE_LENGTH - 1].rstrip() + "…"


def _locator(context: RAGContext) -> dict[str, str]:
    """Freeze the citation's identity so it stays readable if the corpus moves on."""
    fields = {
        "source_id": str(context.source_id),
        "source_type": context.source_type,
        "source_url": context.source_url,
        "court_name": context.court_name,
        "chamber": context.chamber,
        "docket_no": context.docket_no,
        "decision_no": context.decision_no,
        "decision_date": context.decision_date.isoformat() if context.decision_date else None,
        "law_name": context.law_name,
        "law_no": context.law_no,
        "article_no": context.article_no,
        "page_number": str(context.page_number) if context.page_number else None,
    }
    return {key: value for key, value in fields.items() if value}


def _relevance(rank: float) -> float:
    return min(max(float(rank), 0.0), 1.0)


def record_exchange(
    connection: psycopg.Connection,
    *,
    user_id: UUID,
    conversation_id: UUID | None,
    project_id: UUID | None,
    question: str,
    answer: VerifiedAnswer,
    model_name: str,
) -> tuple[UUID, UUID]:
    """Persist the question, the verified answer and the sources it relied on.

    Returns the conversation and assistant message identifiers. Row-level
    security decides whether the caller may write into an existing conversation,
    so a rejected write surfaces as a database error rather than silent success.

    Identifiers are generated here rather than read back with RETURNING: select
    policies are also applied to the returned row, and the row inserted by the
    current statement is not yet visible to the lookups those policies perform,
    so RETURNING would be rejected.
    """
    if conversation_id is None:
        conversation_id = uuid4()
        connection.execute(
            """
            INSERT INTO conversations (id, project_id, created_by, title)
            VALUES (%s, %s, %s, %s)
            """,
            (conversation_id, project_id, user_id, _conversation_title(question)),
        )

    connection.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
        (conversation_id, question),
    )
    message_id = uuid4()
    connection.execute(
        """
        INSERT INTO messages (id, conversation_id, role, content, model_name, metadata)
        VALUES (%s, %s, 'assistant', %s, %s, %s)
        """,
        (
            message_id,
            conversation_id,
            answer.text,
            model_name,
            Jsonb(
                {
                    "grounded": answer.grounded,
                    "unverified_markers": list(answer.unverified_markers),
                }
            ),
        ),
    )

    for position, context in enumerate(answer.contexts, start=1):
        connection.execute(
            """
            INSERT INTO citations (
                message_id,
                document_chunk_id,
                legal_chunk_id,
                citation_order,
                marker,
                source_title,
                source_locator,
                snippet,
                relevance_score
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                message_id,
                context.chunk_id if context.source_type == "document" else None,
                context.chunk_id if context.source_type != "document" else None,
                position,
                f"K{position}",
                context.reference_line,
                Jsonb(_locator(context)),
                context.content[:_SNIPPET_LENGTH],
                _relevance(context.rank),
            ),
        )

    return conversation_id, message_id
