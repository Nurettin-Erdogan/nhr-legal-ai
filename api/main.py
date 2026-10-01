from __future__ import annotations

import asyncio
import logging
import sys
import threading
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.admin_audit import router as admin_audit_router
from api.admin_ingestion import router as admin_ingestion_router
from api.ai.providers import AIProviderError, LOCAL_OLLAMA_PROVIDERS, create_provider
from api.ai.routes import router as ai_router
from api.auth.routes import router as auth_router
from api.config import get_settings
from api.conversations import router as conversations_router
from api.db import database_connection
from api.document_trash import purge_expired
from api.documents import router as documents_router
from api.legal import router as legal_router, warm_slow_counts
from api.office import router as office_router
from api.office_ai import router as office_ai_router
from api.office_public import router as office_public_router
from api.office_trash import router as office_trash_router
from api.projects import router as projects_router
from api.schemas import HealthResponse

logger = logging.getLogger(__name__)


def _warmup_local_model() -> None:
    if "pytest" in sys.modules:
        return
    settings = get_settings()
    if settings.ai_provider not in LOCAL_OLLAMA_PROVIDERS:
        return
    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=min(30.0, settings.ollama_timeout_seconds),
            ollama_max_output_tokens=settings.ollama_max_output_tokens,
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_keep_alive=settings.ollama_keep_alive,
        )
        warmup = getattr(provider, "warmup", None)
        if callable(warmup):
            warmup()
    except AIProviderError:
        logger.info("Ollama ısındırma atlandı; model daha sonra yüklenecek")


_TRASH_PURGE_INTERVAL_SECONDS = 6 * 3600


async def _purge_trash_forever() -> None:
    """Saklama süresi dolan çöp belgeleri düzenli olarak kalıcı siler (docs/office-document-trash.md)."""
    await asyncio.sleep(60)  # açılışı yavaşlatmasın
    while True:
        try:
            await asyncio.to_thread(purge_expired)
        except Exception:  # noqa: BLE001 - temizlik döngüsü hiçbir hatada durmamalı
            logger.exception("Çöp kutusu temizliği başarısız")
        await asyncio.sleep(_TRASH_PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warmup_local_model()
    purge_task = None
    if "pytest" not in sys.modules:
        threading.Thread(target=warm_slow_counts, name="corpus-stats-warmup", daemon=True).start()
        purge_task = asyncio.create_task(_purge_trash_forever())
    yield
    if purge_task is not None:
        purge_task.cancel()


app = FastAPI(
    title="JurisAI API",
    description="Türk hukuku araştırma ve kaynaklı yapay zekâ platformu API'si.",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(legal_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(office_router)
app.include_router(office_trash_router)
app.include_router(office_ai_router)
app.include_router(office_public_router)
app.include_router(admin_ingestion_router)
app.include_router(admin_audit_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL bağlantısı kurulamadı") from exc
    return HealthResponse(status="ok", database="connected")
