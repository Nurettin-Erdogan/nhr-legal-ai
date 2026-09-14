from __future__ import annotations

import asyncio

import psycopg
from fastapi import APIRouter, HTTPException

from api.ai.providers import AIProviderError, create_provider
from api.ai.rag import generate_grounded_answer
from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
from api.ai.retrieval import retrieve_contexts
from api.config import get_settings
from api.db import database_connection
from api.schemas import AIAnswerRequest, AIAnswerResponse, AICitation, AIStatusResponse

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


@router.post("/answer", response_model=AIAnswerResponse)
async def answer_question(request: AIAnswerRequest) -> AIAnswerResponse:
    settings = get_settings()
    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            api_key=settings.gemini_api_key,
            model=settings.ai_model,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    query_embedding = None
    if settings.embedding_api_key:
        try:
            embedding_provider = create_embedding_provider(
                provider_name=settings.embedding_provider,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
            )
            query_embedding = await asyncio.to_thread(
                embedding_provider.embed_query, request.question
            )
        except EmbeddingProviderError:
            # Semantic retrieval is an enhancement; lexical RAG remains available.
            query_embedding = None

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
        answer = await asyncio.to_thread(
            generate_grounded_answer,
            provider,
            question=request.question,
            contexts=contexts,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    citations = [
        AICitation(
            marker=f"K{index}",
            source_id=context.source_id,
            chunk_id=context.chunk_id,
            title=context.title,
            source_url=context.source_url,
            chamber=context.chamber,
            docket_no=context.docket_no,
            decision_no=context.decision_no,
            decision_date=context.decision_date,
            excerpt=context.content[:500],
            rank=context.rank,
        )
        for index, context in enumerate(contexts, start=1)
    ]
    return AIAnswerResponse(
        question=request.question,
        answer=answer,
        provider=provider.name,
        model=provider.model,
        citations=citations,
    )
