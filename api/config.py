from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from dotenv import dotenv_values, load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    admin_database_url: str | None
    cors_origins: tuple[str, ...]
    ai_provider: str
    ai_model: str
    gemini_api_key: str | None
    rag_top_k: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_api_key: str | None
    jwt_secret: str | None
    jwt_expire_minutes: int
    auth_cookie_secure: bool
    allow_registration: bool


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
    gemini_api_key = os.getenv("GEMINI_API_KEY") or file_values.get("GEMINI_API_KEY") or None
    return Settings(
        database_url=_database_url(),
        admin_database_url=(
            os.getenv("DATABASE_ADMIN_URL")
            or file_values.get("DATABASE_ADMIN_URL")
            or None
        ),
        cors_origins=tuple(value.strip() for value in origins.split(",") if value.strip()),
        ai_provider=os.getenv("AI_PROVIDER", "gemini").strip().lower(),
        ai_model=os.getenv("AI_MODEL", "gemini-3.5-flash-lite").strip(),
        gemini_api_key=gemini_api_key,
        rag_top_k=max(1, min(int(os.getenv("RAG_TOP_K", "6")), 12)),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "gemini").strip().lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-2").strip(),
        embedding_dimensions=max(
            1, min(int(os.getenv("EMBEDDING_DIMENSIONS", "768")), 2000)
        ),
        embedding_api_key=(
            os.getenv("EMBEDDING_API_KEY")
            or file_values.get("EMBEDDING_API_KEY")
            or gemini_api_key
        ),
        jwt_secret=os.getenv("JWT_SECRET") or file_values.get("JWT_SECRET") or None,
        jwt_expire_minutes=max(
            5, min(int(os.getenv("JWT_EXPIRE_MINUTES", "480")), 10080)
        ),
        auth_cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes"},
        allow_registration=os.getenv("ALLOW_REGISTRATION", "true").lower()
        in {"1", "true", "yes"},
    )
