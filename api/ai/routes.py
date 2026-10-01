from __future__ import annotations

import json
from time import monotonic
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.ai.pipeline import (
    _embed_question,
    as_citation,
    execute_answer,
    iter_answer_events,
    persist_answer,
)
from api.ai.providers import (
    AIProviderError,
    LOCAL_OLLAMA_PROVIDERS,
    OllamaProvider,
)
from api.ai.research import router as research_router
from api.audit import AuditContext
from api.auth.routes import optional_current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection, database_connection
from api.schemas import AIAnswerRequest, AIAnswerResponse, AIStatusResponse

router = APIRouter(prefix="/api/ai", tags=["ai"])
router.include_router(research_router)

_STATUS_TTL_SECONDS = 30.0
_status_semantic_cache: tuple[float, bool] | None = None

# Re-export for existing tests that patch the route module.
_as_citation = as_citation
_persist = persist_answer


@router.get("/status", response_model=AIStatusResponse)
def ai_status() -> AIStatusResponse:
    settings = get_settings()
    semantic_search_ready = _semantic_search_ready(settings.embedding_model)
    configured = False
    if settings.ai_provider in LOCAL_OLLAMA_PROVIDERS:
        try:
            configured = OllamaProvider(
                model=settings.ai_model,
                name=settings.ai_provider,
                base_url=settings.ollama_base_url,
                timeout_seconds=settings.ollama_timeout_seconds,
            ).is_available()
        except AIProviderError:
            configured = False
    return AIStatusResponse(
        provider=settings.ai_provider,
        model=settings.ai_model,
        configured=configured,
        embedding_model=settings.embedding_model,
        semantic_search_ready=semantic_search_ready,
        ollama_num_ctx=settings.ollama_num_ctx,
        ollama_max_output_tokens=settings.ollama_max_output_tokens,
    )


def _semantic_search_ready(embedding_model: str) -> bool:
    global _status_semantic_cache
    now = monotonic()
    cached = _status_semantic_cache
    if cached is not None and now - cached[0] < _STATUS_TTL_SECONDS:
        return cached[1]
    try:
        with database_connection() as connection:
            ready = bool(
                connection.execute(
                    "SELECT EXISTS (SELECT 1 FROM legal_chunks "
                    "WHERE embedding IS NOT NULL AND embedding_model = %s)",
                    (embedding_model,),
                ).fetchone()["exists"]
            )
    except psycopg.Error:
        ready = False
    _status_semantic_cache = (now, ready)
    return ready


def _require_project_access(user_id: UUID | None, project_id: UUID | None) -> None:
    if project_id is None:
        return
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Proje belgeleriyle çalışmak için oturum açmalısınız",
        )
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            project = connection.execute(
                "SELECT id FROM projects WHERE id = %s AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Proje erişimi doğrulanamadı") from exc
    if project is None:
        raise HTTPException(status_code=404, detail="Proje bulunamadı")


def _require_case_access(user_id: UUID | None, case_id: UUID | None) -> None:
    if case_id is None:
        return
    if user_id is None:
        raise HTTPException(
            status_code=401, detail="Dava belgeleriyle çalışmak için oturum açmalısınız"
        )
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            case = connection.execute(
                "SELECT id FROM office_cases WHERE id = %s", (case_id,)
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Dava erişimi doğrulanamadı") from exc
    # RLS: başkasının davası ile olmayan dava ayırt edilemez.
    if case is None:
        raise HTTPException(status_code=404, detail="Dava bulunamadı")


@router.post("/answer", response_model=AIAnswerResponse)
async def answer_question(
    request: AIAnswerRequest,
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    http_request: Request,
) -> AIAnswerResponse:
    _require_project_access(user_id, request.project_id)
    _require_case_access(user_id, request.case_id)
    response, _timings = await execute_answer(
        request, user_id, audit=AuditContext.from_request(http_request)
    )
    return response


@router.post("/answer/progress")
async def answer_question_progress(
    request: AIAnswerRequest,
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    http_request: Request,
) -> StreamingResponse:
    _require_project_access(user_id, request.project_id)
    _require_case_access(user_id, request.case_id)
    audit = AuditContext.from_request(http_request)

    async def events():
        try:
            async for event in iter_answer_events(request, user_id, audit):
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
        except HTTPException as exc:
            yield json.dumps(
                {"stage": "error", "status": exc.status_code, "detail": exc.detail},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
