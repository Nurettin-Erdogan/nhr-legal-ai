from __future__ import annotations

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.admin_ingestion import router as admin_ingestion_router
from api.ai.routes import router as ai_router
from api.auth.routes import router as auth_router
from api.config import get_settings
from api.db import database_connection
from api.documents import router as documents_router
from api.legal import router as legal_router
from api.projects import router as projects_router
from api.schemas import HealthResponse

app = FastAPI(
    title="NHR Legal AI API",
    description="Türk hukuku araştırma ve kaynaklı yapay zekâ platformu API'si.",
    version="0.1.0",
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(legal_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(documents_router)
app.include_router(admin_ingestion_router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="PostgreSQL bağlantısı kurulamadı") from exc
    return HealthResponse(status="ok", database="connected")
