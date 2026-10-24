from __future__ import annotations

import asyncio
import logging
import sys
import threading
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.account import router as account_router
from api.admin_audit import router as admin_audit_router
from api.admin_ingestion import router as admin_ingestion_router
from api.admin_panel import router as admin_panel_router
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
from api.office_search import router as office_search_router
from api.execution import router as execution_router
from api.service_records import router as service_records_router
from api.uyap_detail import router as uyap_detail_router
from api.uyap_sync import router as uyap_sync_router
from api.uyap_runs import router as uyap_runs_router
from api.uyap_account import router as uyap_account_router
from api.uyap_diagnostics import router as uyap_diagnostics_router
from api.office_ai import router as office_ai_router
from api.document_jobs import router as document_jobs_router
from api.project_documents import router as project_documents_router
from api.integrations import router as integrations_router
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


_REMINDER_MAIL_INTERVAL_SECONDS = 60


async def _send_reminder_mails_forever() -> None:
    """Zamanı gelen e-posta hatırlatmalarını dakikada bir gönderir (SMTP yoksa hiçbir şey yapmaz)."""
    from api.reminder_mailer import send_due_reminders

    await asyncio.sleep(45)
    while True:
        try:
            await asyncio.to_thread(send_due_reminders)
        except Exception:  # noqa: BLE001 - döngü hiçbir hatada durmamalı
            logger.exception("Hatırlatma e-posta döngüsü hatası")
        await asyncio.sleep(_REMINDER_MAIL_INTERVAL_SECONDS)


_WARMUP_QUESTIONS = (
    "kira sözleşmesi tahliye ihtiyaç",
    "işçi kıdem tazminatı fesih",
    "kasten yaralama ceza",
)


def _warm_retrieval_cache() -> None:
    """Açılışta temsilî birkaç arama çalıştırır: veritabanı sayfaları önbelleğe girsin, ilk
    kullanıcı sorusu soğuk önbellekte zaman aşımına düşmesin. Hiçbir hata açılışı etkilemez."""
    try:
        from api.ai.retrieval import retrieve_contexts
        from api.db import database_connection

        with database_connection() as connection:
            for question in _WARMUP_QUESTIONS:
                try:
                    retrieve_contexts(
                        connection, question=question, top_k=3,
                        query_embedding=None, embedding_model=None,
                    )
                except Exception:  # noqa: BLE001 - ısınma denemesi; zaman aşımı beklenen olabilir
                    logger.info("Arama ısınma sorgusu tamamlanamadı: %s", question)
    except Exception:  # noqa: BLE001
        logger.exception("Arama ısınması başlatılamadı")


def _warm_law_list() -> None:
    """Mevzuat listesini açılışta bir kez çıkarır: Mevzuat sayfasına ilk giren kullanıcı ~20 saniye beklemesin."""
    try:
        from api.legal import _load_laws_cached

        _load_laws_cached()
    except Exception:  # noqa: BLE001 - ısınma denemesi; başarısızsa ilk istek listeyi kendi çıkarır
        logger.info("Mevzuat listesi ısındırılamadı; ilk istekte yüklenecek")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warmup_local_model()
    purge_task = None
    reminder_task = None
    if "pytest" not in sys.modules:
        threading.Thread(target=warm_slow_counts, name="corpus-stats-warmup", daemon=True).start()
        threading.Thread(target=_warm_retrieval_cache, name="retrieval-warmup", daemon=True).start()
        threading.Thread(target=_warm_law_list, name="law-list-warmup", daemon=True).start()
        purge_task = asyncio.create_task(_purge_trash_forever())
        reminder_task = asyncio.create_task(_send_reminder_mails_forever())
    yield
    for task in (purge_task, reminder_task):
        if task is not None:
            task.cancel()


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

# Tarayıcı güvenlik başlıkları. API yalnız JSON ve indirilen dosya döndürür: hiçbir yanıt başka sitede çerçevelenmemeli, içerik türü
# tahmin edilmemeli, adres dış sitelere sızmamalıdır. CSP etkileşimli belge sayfalarına (/docs, /redoc) uygulanmaz (kendi betiklerini
# yükler). HSTS yalnız çerez "Secure" iken (yani HTTPS yayında) gönderilir; yerel HTTP geliştirmede anlamsızdır.
_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not request.url.path.startswith(_DOC_PATHS):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.auth_cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


app.include_router(legal_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(projects_router)
app.include_router(conversations_router)
app.include_router(documents_router)
app.include_router(office_search_router)
app.include_router(execution_router)
app.include_router(service_records_router)
app.include_router(uyap_sync_router)
app.include_router(uyap_runs_router)
app.include_router(uyap_account_router)
app.include_router(uyap_diagnostics_router)
app.include_router(uyap_detail_router)
app.include_router(office_router)
app.include_router(office_trash_router)
app.include_router(office_ai_router)
app.include_router(document_jobs_router)
app.include_router(project_documents_router)
app.include_router(integrations_router)
app.include_router(office_public_router)
app.include_router(admin_ingestion_router)
app.include_router(admin_audit_router)
app.include_router(admin_panel_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL bağlantısı kurulamadı") from exc
    return HealthResponse(status="ok", database="connected")
