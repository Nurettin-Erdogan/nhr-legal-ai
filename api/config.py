from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote

from dotenv import dotenv_values, load_dotenv

from api.ai.providers import LOCAL_OLLAMA_PROVIDERS
from api.ai.cloud_provider import DEEPSEEK_DEFAULT_MODEL, DEEPSEEK_MAX_COMPLETION_TOKENS


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
    rag_explanations: bool = False
    # Mevzuat için ikinci anlam vektörü (migration 061; boş = kapalı). Ölçüm: ilk 5'te doğru madde 12/18 -> 17/18.
    legislation_embedding_model: str = ""
    # Serbest cevap + cümle cümle kanıt (api/ai/free_answer.py); kapalıysa ya da başarısız olursa eski sentez yolu çalışır.
    free_answer_enabled: bool = True
    free_answer_local: bool = False
    # Çok parçalı sorularda her parça ayrı çağrıda, paralel yazılır ve denetlenir (api/ai/free_answer.py)
    free_answer_parallel_parts: bool = True
    # Yazmadan önce konusu açıkça ilgisiz kaynakları ayıklar (api/ai/free_answer.py `_drop_unrelated_sources`)
    free_answer_source_triage: bool = True
    # Doğrulanan bölümleri bitiş sırasına göre önizleme olarak gösterir (yalnız denetimden geçmiş cümleler)
    free_answer_stream_verified: bool = True
    # Reddedilen cümlelerin gerekçeleri ilk denetimde yazılmaz, arka planda istenir (yalnız yeniden deneme bekler)
    free_answer_defer_reasons: bool = True
    # Önceden hazırlanmış, kaynaklarıyla doğrulanmış cevaplar (api/ai/warm_cache.py; yalnız genel soru, kaynaklar değişmemişse)
    warm_answer_cache_enabled: bool = True
    official_web_research_enabled: bool = False
    # Doğal cevap + ayrı iddia denetimi. Kapalıysa eski tam alıntı akışı kullanılır.
    rag_natural_answers: bool = True
    # Enable only after end-to-end acceptance; plans do not replace grounding.
    rag_research_planning: bool = False
    rag_synthesis_context_chars: int = 24000
    # Bulut modeli (varsayılan kapalı): yalnız genel hukuk sorularında kullanılır; bkz. api/ai/cloud_provider.py.
    cloud_ai_provider: str = ""
    cloud_ai_model: str = ""
    cloud_ai_plan_model: str = ""
    # Yazarla aynı sağlayıcıda, ama denetim çağrıları için ayrı (genelde daha güçlü) model; boşsa yazarla aynı model.
    cloud_ai_check_model: str = ""
    cloud_ai_api_key: str = field(default="", repr=False)
    cloud_ai_max_output_tokens: int = 1024
    cloud_ai_timeout_seconds: float = 60.0
    cloud_ai_reasoning_effort: str = "low"
    # Ayrı, sunucu tarafı araştırma profili; genel sohbeti veya özel belge akışını değiştirmez.
    deep_research_cloud_enabled: bool = False
    deep_research_ai_model: str = "deepseek-v4-pro"
    deep_research_ai_api_key: str = field(default="", repr=False)
    deep_research_ai_provider: str = "deepseek"
    deep_research_ai_max_output_tokens: int = 0
    deep_research_ai_timeout_seconds: float = 180.0
    deep_research_ai_reasoning_effort: str = "max"


def _cloud_output_tokens(name: str, *, deepseek: bool) -> int:
    value = int(os.getenv(name, "0" if deepseek else "1024"))
    if deepseek:
        # Yalnız sağlayıcının teknik aralığı. 0 = uygulama kotası yok.
        return max(0, min(value, DEEPSEEK_MAX_COMPLETION_TOKENS))
    return max(256, min(value, 8192))


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
    origins = os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    ai_provider = os.getenv("AI_PROVIDER", "deepseek").strip().lower()
    cloud_provider = os.getenv("CLOUD_AI_PROVIDER", "").strip().lower()
    cloud_key_name = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
                      "deepseek": "DEEPSEEK_API_KEY", "openrouter": "OPENROUTER_API_KEY",
                      "gemini": "GEMINI_API_KEY", "bedrock": "AWS_BEARER_TOKEN_BEDROCK"}.get(cloud_provider, "")
    research_provider = os.getenv("DEEP_RESEARCH_AI_PROVIDER", "deepseek").strip().lower()
    research_key_name = "OPENROUTER_API_KEY" if research_provider == "openrouter" else "DEEPSEEK_API_KEY"
    return Settings(
        database_url=_database_url(),
        admin_database_url=(
            os.getenv("DATABASE_ADMIN_URL")
            or file_values.get("DATABASE_ADMIN_URL")
            or None
        ),
        cors_origins=tuple(value.strip() for value in origins.split(",") if value.strip()),
        ai_provider=ai_provider,
        rag_explanations=os.getenv("RAG_EXPLANATIONS", "false").lower() in {"1", "true", "yes"},
        rag_natural_answers=os.getenv("RAG_NATURAL_ANSWERS", "true").lower() in {"1", "true", "yes"},
        rag_research_planning=os.getenv("RAG_RESEARCH_PLANNING", "false").lower() in {"1", "true", "yes"},
        rag_synthesis_context_chars=max(4000, min(int(os.getenv("RAG_SYNTHESIS_CONTEXT_CHARS", "24000")), 64000)),
        ai_model=os.getenv("AI_MODEL", "deepseek-r1:8b").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip(),
        ollama_timeout_seconds=max(
            1.0, min(float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")), 600.0)
        ),
        ollama_max_output_tokens=max(
            64, min(int(os.getenv("OLLAMA_MAX_OUTPUT_TOKENS", "256")), 4096)
        ),
        ollama_num_ctx=max(512, min(int(os.getenv("OLLAMA_NUM_CTX", "2048")), 8192)),
        ollama_keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip() or "30m",
        rag_top_k=max(
            1, min(int(os.getenv("RAG_TOP_K", "6")), 12)
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
        cloud_ai_provider=cloud_provider,
        legislation_embedding_model=os.getenv("LEGISLATION_EMBEDDING_MODEL", "bge-m3").strip(),
        free_answer_enabled=os.getenv("FREE_ANSWER_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        free_answer_local=os.getenv("FREE_ANSWER_LOCAL", "false").strip().lower() in {"1", "true", "yes", "on"},
        free_answer_parallel_parts=os.getenv("FREE_ANSWER_PARALLEL_PARTS", "true").strip().lower() in {"1", "true", "yes", "on"},
        free_answer_source_triage=os.getenv("FREE_ANSWER_SOURCE_TRIAGE", "true").strip().lower() in {"1", "true", "yes", "on"},
        free_answer_stream_verified=os.getenv("FREE_ANSWER_STREAM_VERIFIED", "true").strip().lower() in {"1", "true", "yes", "on"},
        free_answer_defer_reasons=os.getenv("FREE_ANSWER_DEFER_REASONS", "true").strip().lower() in {"1", "true", "yes", "on"},
        warm_answer_cache_enabled=os.getenv("WARM_ANSWER_CACHE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        official_web_research_enabled=os.getenv("OFFICIAL_WEB_RESEARCH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        cloud_ai_check_model=os.getenv("CLOUD_AI_CHECK_MODEL", "").strip(),
        cloud_ai_plan_model=os.getenv("CLOUD_AI_PLAN_MODEL", {"gemini": "gemini-3.1-flash-lite"}.get(cloud_provider, "")).strip(),
        cloud_ai_model=os.getenv("CLOUD_AI_MODEL", DEEPSEEK_DEFAULT_MODEL if cloud_provider == "deepseek" else "").strip(),
        cloud_ai_api_key=(os.getenv(cloud_key_name) or file_values.get(cloud_key_name) or "").strip() if cloud_key_name else "",
        cloud_ai_max_output_tokens=_cloud_output_tokens("CLOUD_AI_MAX_OUTPUT_TOKENS", deepseek=cloud_provider in {"deepseek", "openrouter", "gemini", "bedrock"}),
        cloud_ai_timeout_seconds=max(5.0, min(float(os.getenv(
            "CLOUD_AI_TIMEOUT_SECONDS", "90" if cloud_provider == "deepseek" else "60"
        )), 300.0)),
        cloud_ai_reasoning_effort=os.getenv("CLOUD_AI_REASONING_EFFORT", "low").strip().lower(),
        deep_research_cloud_enabled=os.getenv("DEEP_RESEARCH_CLOUD_ENABLED", "false").lower()
        in {"1", "true", "yes"},
        deep_research_ai_model=os.getenv("DEEP_RESEARCH_AI_MODEL", "deepseek-v4-pro").strip() or "deepseek-v4-pro",
        deep_research_ai_provider=research_provider,
        deep_research_ai_api_key=(os.getenv(research_key_name) or file_values.get(research_key_name) or "").strip(),
        deep_research_ai_max_output_tokens=_cloud_output_tokens("DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS", deepseek=True),
        deep_research_ai_timeout_seconds=max(5.0, min(float(os.getenv(
            "DEEP_RESEARCH_AI_TIMEOUT_SECONDS", "180"
        )), 300.0)),
        deep_research_ai_reasoning_effort=os.getenv("DEEP_RESEARCH_AI_REASONING_EFFORT", "max").strip().lower(),
    )
