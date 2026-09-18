"""Shared grounded-answer pipeline: retrieve, cache, generate, verify, persist."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
from fastapi import HTTPException
from psycopg.errors import InsufficientPrivilege

from api.ai.cache import answer_cache, answer_cache_key, source_fingerprint
from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
from api.ai.history import record_exchange
from api.ai.providers import AIProvider, AIProviderError, create_provider
from api.ai.rag import RAGContext, generate_grounded_answer
from api.ai.retrieval import retrieve_contexts, retrieve_document_contexts
from api.ai.verification import VerifiedAnswer, verify_answer
from api.config import get_settings
from api.db import authenticated_database_connection, database_connection
from api.schemas import AIAnswerRequest, AIAnswerResponse, AICitation

logger = logging.getLogger(__name__)

StageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None]
_generation_lock = asyncio.Lock()


@dataclass(slots=True)
class PipelineTimings:
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0
    prompt_build_ms: float = 0.0
    llm_ms: float = 0.0
    verification_ms: float = 0.0
    persist_ms: float = 0.0
    total_ms: float = 0.0
    from_cache: bool = False
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def as_citation(position: int, context: RAGContext) -> AICitation:
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
        page_number=context.page_number,
        version_date=context.version_date,
        effective_from=context.effective_from,
        effective_to=context.effective_to,
        source_version=context.source_version,
        revision=context.revision,
        excerpt=context.content[:500],
        rank=context.rank,
    )


def _response_from_verified(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    provider: AIProvider,
    conversation_id: UUID | None,
    message_id: UUID | None,
    from_cache: bool,
) -> AIAnswerResponse:
    return AIAnswerResponse(
        question=request.question,
        as_of=request.as_of,
        answer=answer.text,
        provider=provider.name,
        model=provider.model,
        citations=[
            as_citation(position, context)
            for position, context in enumerate(answer.contexts, start=1)
        ],
        grounded=answer.grounded,
        unverified_markers=list(answer.unverified_markers),
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=from_cache,
    )


def _payload_from_response(response: AIAnswerResponse) -> dict[str, Any]:
    return response.model_dump(mode="json", exclude={"conversation_id", "message_id", "from_cache"})


async def _embed_question(question: str) -> list[float] | None:
    settings = get_settings()
    try:
        provider = create_embedding_provider(
            provider_name=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds),
        )
        return await asyncio.to_thread(provider.embed_query, question)
    except EmbeddingProviderError:
        logger.warning("Soru embedding'i üretilemedi; lexical RAG kullanılacak")
        return None


def persist_answer(
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
                as_of=request.as_of,
            )
    except InsufficientPrivilege as exc:
        raise HTTPException(
            status_code=403,
            detail="Bu konuşmaya veya projeye yazma yetkiniz yok",
        ) from exc
    except psycopg.Error:
        logger.exception("Sohbet geçmişi kaydedilemedi")
        return None, None


def _retrieve(
    request: AIAnswerRequest,
    *,
    user_id: UUID | None,
    query_embedding: list[float] | None,
    top_k: int,
    embedding_model: str,
) -> list[RAGContext]:
    if request.project_id is not None:
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Proje belgeleriyle çalışmak için oturum açmalısınız",
            )
        with authenticated_database_connection(str(user_id)) as connection:
            legal_contexts = retrieve_contexts(
                connection,
                question=request.question,
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                as_of=request.as_of,
            )
            document_contexts = retrieve_document_contexts(
                connection,
                question=request.question,
                project_id=str(request.project_id),
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
            return sorted(
                (*legal_contexts, *document_contexts),
                key=lambda context: context.rank,
                reverse=True,
            )[:top_k]
    with database_connection() as connection:
        return retrieve_contexts(
            connection,
            question=request.question,
            top_k=top_k,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            as_of=request.as_of,
        )


async def execute_answer(
    request: AIAnswerRequest,
    user_id: UUID | None,
    *,
    on_stage: StageCallback | None = None,
) -> tuple[AIAnswerResponse, PipelineTimings]:
    settings = get_settings()
    timings = PipelineTimings()
    started = monotonic()

    async def emit(stage: str, **extra: Any) -> None:
        if on_stage is None:
            return
        result = on_stage({"stage": stage, **extra})
        if asyncio.iscoroutine(result):
            await result

    await emit("searching")
    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=settings.ollama_timeout_seconds,
            ollama_max_output_tokens=settings.ollama_max_output_tokens,
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_keep_alive=settings.ollama_keep_alive,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    embed_started = monotonic()
    query_embedding = (
        await _embed_question(request.question) if settings.rag_query_embedding else None
    )
    timings.embedding_ms = (monotonic() - embed_started) * 1000 if query_embedding else 0.0

    retrieval_started = monotonic()
    try:
        contexts = await asyncio.to_thread(
            _retrieve,
            request,
            user_id=user_id,
            query_embedding=query_embedding,
            top_k=settings.rag_top_k,
            embedding_model=settings.embedding_model,
        )
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Hukuk kaynakları aranamadı") from exc
    timings.retrieval_ms = (monotonic() - retrieval_started) * 1000

    if not contexts:
        raise HTTPException(
            status_code=422,
            detail="Bu soru için mevcut korpusta yeterli kaynak bulunamadı",
        )

    await emit("sources_found", count=len(contexts))
    fingerprint = source_fingerprint(contexts)
    cache_key = answer_cache_key(
        question=request.question,
        project_id=request.project_id,
        as_of=request.as_of,
        model=provider.model,
        fingerprint=fingerprint,
    )
    cached = answer_cache.get(cache_key)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    if cached is not None:
        timings.from_cache = True
        cached_answer = VerifiedAnswer(
            text=cached["answer"],
            contexts=tuple(
                context
                for context in contexts
                if str(context.chunk_id)
                in {item["chunk_id"] for item in cached["citations"]}
            ),
            unverified_markers=tuple(cached.get("unverified_markers") or ()),
        )
        # Keep citation order from the cached payload rather than retrieval rank.
        cited_ids = [item["chunk_id"] for item in cached["citations"]]
        by_id = {str(context.chunk_id): context for context in contexts}
        ordered = tuple(by_id[chunk_id] for chunk_id in cited_ids if chunk_id in by_id)
        if len(ordered) != len(cited_ids):
            cached = None
        else:
            cached_answer = VerifiedAnswer(
                text=cached["answer"],
                contexts=ordered,
                unverified_markers=tuple(cached.get("unverified_markers") or ()),
            )
            persist_started = monotonic()
            if user_id is not None:
                conversation_id, message_id = await asyncio.to_thread(
                    persist_answer,
                    request,
                    cached_answer,
                    user_id=user_id,
                    model_name=provider.model,
                )
            timings.persist_ms = (monotonic() - persist_started) * 1000
            timings.total_ms = (monotonic() - started) * 1000
            response = _response_from_verified(
                request,
                cached_answer,
                provider=provider,
                conversation_id=conversation_id,
                message_id=message_id,
                from_cache=True,
            )
            await emit("done", result=response.model_dump(mode="json"))
            return response, timings

    await emit("generating")
    try:
        async with _generation_lock:
            llm_started = monotonic()
            raw_answer = await asyncio.to_thread(
                generate_grounded_answer,
                provider,
                question=request.question,
                contexts=contexts,
                max_context_chars=settings.rag_context_chars,
            )
            timings.llm_ms = (monotonic() - llm_started) * 1000
    except AIProviderError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    usage = getattr(provider, "last_usage", None)
    if usage is not None:
        timings.prompt_eval_count = usage.prompt_eval_count
        timings.eval_count = usage.eval_count

    await emit("verifying")
    verify_started = monotonic()
    answer = verify_answer(raw_answer, contexts)
    timings.verification_ms = (monotonic() - verify_started) * 1000
    if not answer.grounded:
        raise HTTPException(
            status_code=422,
            detail="Model doğrulanabilir bir kaynak atfı üretmedi; yanıt gösterilmiyor",
        )

    persist_started = monotonic()
    if user_id is not None:
        conversation_id, message_id = await asyncio.to_thread(
            persist_answer,
            request,
            answer,
            user_id=user_id,
            model_name=provider.model,
        )
    timings.persist_ms = (monotonic() - persist_started) * 1000
    response = _response_from_verified(
        request,
        answer,
        provider=provider,
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=False,
    )
    answer_cache.put(cache_key, _payload_from_response(response))
    timings.total_ms = (monotonic() - started) * 1000
    await emit("done", result=response.model_dump(mode="json"))
    return response, timings


async def iter_answer_events(
    request: AIAnswerRequest,
    user_id: UUID | None,
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_stage(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await execute_answer(request, user_id, on_stage=on_stage)
        except HTTPException as exc:
            await queue.put(
                {"stage": "error", "status": exc.status_code, "detail": exc.detail}
            )
        except Exception:
            logger.exception("AI yanıt üretimi başarısız")
            await queue.put(
                {
                    "stage": "error",
                    "status": 500,
                    "detail": "AI yanıtı üretilemedi",
                }
            )
        finally:
            await queue.put({"stage": "_end"})

    task = asyncio.create_task(run())
    try:
        while True:
            event = await queue.get()
            if event.get("stage") == "_end":
                break
            yield event
    finally:
        await task
