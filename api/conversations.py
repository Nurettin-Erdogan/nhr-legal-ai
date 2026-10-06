"""Kullanıcının sohbet geçmişi: liste, tek sohbet (atıflarıyla) ve silme.

Erişim kontrolü tamamen PostgreSQL RLS'e dayanır: her sorgu `authenticated_database_connection`
ile kullanıcının kimliği altında çalışır; proje sohbetlerini proje üyeleri, projesiz sohbetleri
yalnız sahibi görür.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from api.audit import CONVERSATION_DELETE, AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationSummary(BaseModel):
    id: UUID
    title: str | None
    project_id: UUID | None
    created_at: datetime
    last_message_at: datetime
    message_count: int


class ConversationCitation(BaseModel):
    marker: str
    source_id: UUID | None = None
    source_type: str | None = None
    reference: str
    source_url: str | None = None
    excerpt: str | None = None
    verification: str = "official"


class ConversationMessage(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime
    model_name: str | None = None
    grounded: bool | None = None
    unverified_markers: list[str] = Field(default_factory=list)
    citations: list[ConversationCitation] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    id: UUID
    title: str | None
    project_id: UUID | None
    created_at: datetime
    messages: list[ConversationMessage]


_LIST_SQL = """
SELECT
    conversation.id,
    conversation.title,
    conversation.project_id,
    conversation.created_at,
    COALESCE(stats.last_message_at, conversation.created_at) AS last_message_at,
    stats.message_count
FROM conversations AS conversation
CROSS JOIN LATERAL (
    SELECT max(message.created_at) AS last_message_at, count(*)::int AS message_count
    FROM messages AS message
    WHERE message.conversation_id = conversation.id AND message.deleted_at IS NULL
) AS stats
WHERE conversation.deleted_at IS NULL
  AND stats.message_count > 0
  {project_filter}
ORDER BY COALESCE(stats.last_message_at, conversation.created_at) DESC
LIMIT %(limit)s
"""

_CONVERSATION_SQL = """
SELECT id, title, project_id, created_at
FROM conversations
WHERE id = %s AND deleted_at IS NULL
"""

_MESSAGES_SQL = """
SELECT id, role, content, model_name, metadata, created_at
FROM messages
WHERE conversation_id = %s
  AND deleted_at IS NULL
  AND role IN ('user', 'assistant')
ORDER BY created_at, id
"""

# Atıfın doğrulama durumu cevap üretildiği andaki değil, kaynağın şimdiki durumuna göredir:
# aradan geçen sürede resmî portalla doğrulanmış bir karar artık "official" görünür.
_CITATIONS_SQL = """
SELECT
    citation.message_id,
    citation.citation_order,
    citation.marker,
    citation.source_title,
    citation.source_locator,
    citation.snippet,
    citation.document_chunk_id,
    source.ingestion_method,
    source.ingest_status
FROM citations AS citation
JOIN messages AS message ON message.id = citation.message_id
LEFT JOIN legal_chunks AS chunk ON chunk.id = citation.legal_chunk_id
LEFT JOIN legal_sources AS source ON source.id = chunk.legal_source_id
WHERE message.conversation_id = %s
ORDER BY citation.message_id, citation.citation_order
"""

_DELETE_SQL = """
UPDATE conversations
SET deleted_at = NOW(), deleted_by = %s
WHERE id = %s AND deleted_at IS NULL
"""


def citation_verification(
    *,
    document_chunk_id: UUID | None,
    ingestion_method: str | None,
    ingest_status: str | None,
) -> str:
    """Kaynağın şimdiki durumuna göre rozet: belge / resmî / üçüncü taraf."""
    if document_chunk_id is not None:
        return "user_document"
    return "official" if ingest_status == "ready" else "third_party"


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _citation_from_row(row: dict[str, Any]) -> ConversationCitation:
    locator = row["source_locator"] or {}
    return ConversationCitation(
        marker=row["marker"],
        source_id=_as_uuid(locator.get("source_id")),
        source_type=locator.get("source_type"),
        reference=row["source_title"],
        source_url=locator.get("source_url"),
        excerpt=row["snippet"],
        verification=citation_verification(
            document_chunk_id=row["document_chunk_id"],
            ingestion_method=row["ingestion_method"],
            ingest_status=row["ingest_status"],
        ),
    )


def build_messages(
    message_rows: list[dict[str, Any]], citation_rows: list[dict[str, Any]]
) -> list[ConversationMessage]:
    citations_by_message: dict[UUID, list[ConversationCitation]] = {}
    for row in citation_rows:
        citations_by_message.setdefault(row["message_id"], []).append(
            _citation_from_row(row)
        )
    messages = []
    for row in message_rows:
        metadata = row["metadata"] or {}
        assistant = row["role"] == "assistant"
        messages.append(
            ConversationMessage(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
                model_name=row["model_name"],
                grounded=metadata.get("grounded") if assistant else None,
                unverified_markers=list(metadata.get("unverified_markers") or [])
                if assistant
                else [],
                citations=citations_by_message.get(row["id"], []),
                summary=[str(item) for item in (metadata.get("summary") or [])][:8] if assistant else [],
            )
        )
    return messages


@router.get("", response_model=list[ConversationSummary])
def list_conversations(
    user_id: Annotated[UUID, Depends(current_user_id)],
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ConversationSummary]:
    sql = _LIST_SQL.format(
        project_filter="AND conversation.project_id = %(project_id)s"
        if project_id is not None
        else ""
    )
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                sql, {"limit": limit, "project_id": project_id}
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("Sohbet listesi alınamadı")
        raise HTTPException(status_code=503, detail="Sohbetler alınamadı") from exc
    return [ConversationSummary(**row) for row in rows]


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
) -> ConversationDetail:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            conversation = connection.execute(
                _CONVERSATION_SQL, (conversation_id,)
            ).fetchone()
            if conversation is None:
                raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
            message_rows = connection.execute(
                _MESSAGES_SQL, (conversation_id,)
            ).fetchall()
            citation_rows = connection.execute(
                _CITATIONS_SQL, (conversation_id,)
            ).fetchall()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        logger.exception("Sohbet alınamadı")
        raise HTTPException(status_code=503, detail="Sohbet alınamadı") from exc
    return ConversationDetail(
        **conversation, messages=build_messages(message_rows, citation_rows)
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    http_request: Request,
) -> Response:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            deleted = connection.execute(
                _DELETE_SQL, (user_id, conversation_id)
            ).rowcount
            if deleted:
                record_event(
                    connection,
                    action=CONVERSATION_DELETE,
                    actor_user_id=user_id,
                    context=AuditContext.from_request(http_request),
                    entity_type="conversation",
                    entity_id=conversation_id,
                )
    except psycopg.errors.InsufficientPrivilege as exc:
        raise HTTPException(
            status_code=403, detail="Bu sohbeti silme yetkiniz yok"
        ) from exc
    except psycopg.Error as exc:
        logger.exception("Sohbet silinemedi")
        raise HTTPException(status_code=503, detail="Sohbet silinemedi") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
