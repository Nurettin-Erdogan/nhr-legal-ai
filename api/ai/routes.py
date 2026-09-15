from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import InsufficientPrivilege

from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
from api.ai.history import record_exchange
from api.ai.providers import AIProviderError, create_provider
from api.ai.rag import RAGContext, generate_grounded_answer
from api.ai.retrieval import retrieve_contexts
from api.ai.verification import VerifiedAnswer, verify_answer
from api.auth.routes import optional_current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection, database_connection
from api.schemas import AIAnswerRequest, AIAnswerResponse, AICitation, AIStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", response_model=AIStatusResponse)
def ai_status() -> AIStatusResponse:
    settings = get_settings()
    try:
        with database_connection() as connection:
            semantic_search_ready = bool(
                connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM legal_chunks "
                    "WHERE embedding IS NOT NULL AND embedding_model = %s)",
                    (settings.embedding_model,),
                ).fetchone()["exists"]
            )
    except psycopg.Error:
        semantic_search_ready = False
    return AIStatusResponse(
        provider=settings.ai_provider,
        model=settings.ai_model,
        configured=bool(settings.gemini_api_key) if settings.ai_provider == "gemini" else False,
        embedding_model=settings.embedding_model,
        semantic_search_ready=semantic_search_ready,
    )


def _as_citation(position: int, context: RAGContext) -> AICitation:
    return AICitation(
        marker=f"K{position}",
        source_id=context.source_id,
        chunk_id=context.chunk_id,
        source_type=context.source_type,
        title=context.title,
        reference=context.reference_line,
        source_url=context.source_url,
        court_name=context.court_name,
        chamber=context.chamber,
        docket_no=context.docket_no,
        decision_no=context.decision_no,
        decision_date=context.decision_date,
        law_name=context.law_name,
        law_no=context.law_no,
        article_no=context.article_no,
        excerpt=context.content[:500],
        rank=context.rank,
    )


async def _embed_question(question: str) -> list[float] | None:
    settings = get_settings()
    if not settings.embedding_api_key:
        return None
    try:
        provider = create_embedding_provider(
            provider_name=settings.embedding_provider,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        return await asyncio.to_thread(provider.embed_query, question)
    except EmbeddingProviderError:
        # Semantic retrieval is an enhancement; lexical RAG remains available.
        return None


def _persist(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    user_id: UUID,
    model_name: str,
) -> tuple[UUID | None, UUID | None]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            return record_exchange(
                connection,
                user_id=user_id,
                conversation_id=request.conversation_id,
                project_id=request.project_id,
                question=request.question,
                answer=answer,
                model_name=model_name,
            )
    except InsufficientPrivilege as exc:
        raise HTTPException(
            status_code=403,
            detail="Bu konuşmaya veya projeye yazma yetkiniz yok",
        ) from exc
    except psycopg.Error:
        # The answer is already grounded and verified; deliver it but make the
        # missing audit trail visible through the null conversation identifiers.
        logger.exception("Sohbet geçmişi kaydedilemedi")
        return None, None


@router.post("/answer", response_model=AIAnswerResponse)
async def answer_question(
    request: AIAnswerRequest,
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
) -> AIAnswerResponse:
    settings = get_settings()
    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            api_key=settings.gemini_api_key,
            model=settings.ai_model,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    query_embedding = await _embed_question(request.question)

    try:
        with database_connection() as connection:
            contexts = retrieve_contexts(
                connection,
                question=request.question,
                top_k=settings.rag_top_k,
                query_embedding=query_embedding,
                embedding_model=settings.embedding_model,
            )
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Hukuk kaynakları aranamadı") from exc

    if not contexts:
        raise HTTPException(
            status_code=422,
            detail="Bu soru için mevcut korpusta yeterli kaynak bulunamadı",
        )

    try:
        raw_answer = await asyncio.to_thread(
            generate_grounded_answer,
            provider,
            question=request.question,
            contexts=contexts,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    answer = verify_answer(raw_answer, contexts)

    conversation_id: UUID | None = None
    message_id: UUID | None = None
    if user_id is not None:
        conversation_id, message_id = await asyncio.to_thread(
            _persist, request, answer, user_id=user_id, model_name=provider.model
        )

    return AIAnswerResponse(
        question=request.question,
        answer=answer.text,
        provider=provider.name,
        model=provider.model,
        citations=[
            _as_citation(position, context)
            for position, context in enumerate(answer.contexts, start=1)
        ],
        grounded=answer.grounded,
        unverified_markers=list(answer.unverified_markers),
        conversation_id=conversation_id,
        message_id=message_id,
    )
