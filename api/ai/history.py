from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from api.ai.rag import RAGContext
from api.ai.verification import VerifiedAnswer

_TITLE_LENGTH = 80
_SNIPPET_LENGTH = 500


class ConversationScopeMismatch(ValueError):
    """Sohbet başka kapsamla devam ettirilemez; kayıt öncesi de kontrol edilir."""


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
        "version_date": context.version_date.isoformat() if context.version_date else None,
        "effective_from": (
            context.effective_from.isoformat() if context.effective_from else None
        ),
        "effective_to": context.effective_to.isoformat() if context.effective_to else None,
        "source_version": context.source_version,
        "revision": str(context.revision) if context.revision is not None else None,
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
    as_of: date | None = None,
    case_id: UUID | None = None,
    office_project_id: UUID | None = None,
    selected_document_ids: list[UUID] | None = None,
    document_scope: dict | None = None,
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
            INSERT INTO conversations (id, project_id, created_by, title, case_id, office_project_id, selected_document_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (conversation_id, project_id, user_id, _conversation_title(question), case_id, office_project_id, selected_document_ids or []),
        )
    else:
        row = connection.execute(
            "SELECT project_id,case_id,office_project_id,selected_document_ids FROM conversations "
            "WHERE id=%s AND deleted_at IS NULL FOR UPDATE", (conversation_id,),
        ).fetchone()
        if row is None or (row['project_id'], row['case_id'], row['office_project_id'], set(row['selected_document_ids'])) != (
            project_id, case_id, office_project_id, set(selected_document_ids or []),
        ):
            raise ConversationScopeMismatch("Sohbetin kaynak kapsamı değişti. Yeni sohbet başlatın.")

    connection.execute(
        "INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'user', %s)",
        (uuid4(), conversation_id, question),
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
                    "as_of": as_of.isoformat() if as_of else None,
                    **({"document_scope": document_scope} if document_scope is not None else {}),
                    **({"summary": list(answer.summary)} if answer.summary else {}),
                }
            ),
        ),
    )

    for position, context in enumerate(answer.contexts, start=1):
        connection.execute(
            """
            INSERT INTO citations (
                id,
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid4(),
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
