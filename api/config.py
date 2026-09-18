from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from dotenv import dotenv_values, load_dotenv

from api.ai.providers import LOCAL_OLLAMA_PROVIDERS


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    admin_database_url: str | None
    cors_origins: tuple[str, ...]
    ai_provider: str
    ai_model: str
    ollama_base_url: str
    ollama_timeout_seconds: float
    ollama_max_output_tokens: int
    ollama_num_ctx: int
    ollama_keep_alive: str
    rag_top_k: int
    rag_context_chars: int
    rag_query_embedding: bool
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    jwt_secret: str | None
    jwt_expire_minutes: int
    auth_cookie_secure: bool
    allow_registration: bool
    document_storage_dir: str
    max_document_size_bytes: int


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(
            "DATABASE_URL veya PostgreSQL ortam değişkenleri eksik: " + ", ".join(missing)
        )

    user = quote(os.environ["POSTGRES_USER"], safe="")
    password = quote(os.environ["POSTGRES_PASSWORD"], safe="")
    database = quote(os.environ["POSTGRES_DB"], safe="")
    port = os.getenv("POSTGRES_PORT", "5433")
    return f"postgresql://{user}:{password}@localhost:{port}/{database}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    file_values = dotenv_values(".env")
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    ai_provider = os.getenv("AI_PROVIDER", "deepseek").strip().lower()
    return Settings(
        database_url=_database_url(),
        admin_database_url=(
            os.getenv("DATABASE_ADMIN_URL")
            or file_values.get("DATABASE_ADMIN_URL")
            or None
        ),
        cors_origins=tuple(value.strip() for value in origins.split(",") if value.strip()),
        ai_provider=ai_provider,
        ai_model=os.getenv("AI_MODEL", "deepseek-r1:8b").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip(),
        ollama_timeout_seconds=max(
            1.0, min(float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")), 600.0)
        ),
        ollama_max_output_tokens=max(
            64, min(int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "768")), 4096)
        ),
        ollama_num_ctx=max(512, min(int(os.getenv("OLLAMA_NUM_CTX", "1536")), 8192)),
        ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip() or "30m",
        rag_top_k=max(
            1, min(int(os.getenv("RAG_TOP_K", "2" if ai_provider in LOCAL_OLLAMA_PROVIDERS else "6")), 12)
        ),
        rag_context_chars=max(400, min(int(os.getenv("RAG_CONTEXT_CHARS", "800")), 4000)),
        rag_query_embedding=os.getenv(
            "RAG_QUERY_EMBEDDING",
            "false" if ai_provider in LOCAL_OLLAMA_PROVIDERS else "true",
        ).lower()
        in {"1", "true", "yes"},
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip(),
        embedding_dimensions=max(
            1, min(int(os.getenv("EMBEDDING_DIMENSIONS", "768")), 2000)
        ),
        jwt_secret=os.getenv("JWT_SECRET") or file_values.get("JWT_SECRET") or None,
        jwt_expire_minutes=max(
            5, min(int(os.getenv("JWT_EXPIRE_MINUTES", "480")), 10080)
        ),
        auth_cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes"},
        allow_registration=os.getenv("ALLOW_REGISTRATION", "true").lower()
        in {"1", "true", "yes"},
        document_storage_dir=os.getenv("DOCUMENT_STORAGE_DIR", "uploads").strip()
        or "uploads",
        max_document_size_bytes=max(
            1, min(int(os.getenv("MAX_DOCUMENT_SIZE_MB", "10")), 50)
        )
        * 1024
        * 1024,
    )
