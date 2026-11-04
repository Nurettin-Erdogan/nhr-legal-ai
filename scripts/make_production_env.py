"""Sunucu için `.env.production` üretir: yerel `.env`den yalnız AI/gömme ayarlarını alır, gizli değerleri yeniden üretir.

    .\\.venv\\Scripts\\python.exe scripts\\make_production_env.py --site 13-60-1-2.sslip.io --out E:\\JurisAI\\env.production

Yeni üretilenler (yereldeki değerlerle aynı OLMAZ): JWT_SECRET, veritabanı parolaları. Veritabanı parolaları geri yüklemeden sonra
`ALTER ROLE` ile değiştirilir (deploy/README.md). Gizli değerler ekrana yazılmaz; dosya depoya girmez, yalnız `--out` yoluna yazılır.
Yerelden olduğu gibi taşınanlar: bulut AI sağlayıcısı ve anahtarı (Bedrock), model adları, gömme ayarları, resmî web araştırması.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Yerel .env'den olduğu gibi alınan anahtarlar (yerel makineye özgü adresler ve parolalar alınmaz).
CARRY = (
    "AI_PROVIDER", "AI_MODEL", "CLOUD_AI_PROVIDER", "CLOUD_AI_MODEL", "CLOUD_AI_REASONING_EFFORT", "CLOUD_AI_MAX_OUTPUT_TOKENS",
    "CLOUD_AI_TIMEOUT_SECONDS", "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION", "AWS_DEFAULT_REGION", "BEDROCK_REGION",
    "DEEP_RESEARCH_CLOUD_ENABLED", "DEEP_RESEARCH_AI_PROVIDER", "DEEP_RESEARCH_AI_MODEL", "DEEP_RESEARCH_AI_REASONING_EFFORT",
    "DEEP_RESEARCH_AI_MAX_OUTPUT_TOKENS", "DEEP_RESEARCH_AI_TIMEOUT_SECONDS", "OLLAMA_TIMEOUT_SECONDS", "OLLAMA_MAX_OUTPUT_TOKENS",
    "OLLAMA_NUM_CTX", "OLLAMA_KEEP_ALIVE", "RAG_TOP_K", "RAG_CONTEXT_CHARS", "RAG_QUERY_EMBEDDING", "RAG_EXPLANATIONS",
    "RAG_NATURAL_ANSWERS", "RAG_SYNTHESIS_CONTEXT_CHARS", "EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS",
    "OFFICIAL_WEB_RESEARCH_ENABLED",
)


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = match.group(2)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", required=True, help="Alan adı (ör. 13-60-1-2.sslip.io); https:// olmadan")
    parser.add_argument("--out", required=True, help="Çıktı dosyası (depo dışında olmalı)")
    parser.add_argument("--source", default=str(ROOT / ".env"))
    args = parser.parse_args()

    out = Path(args.out).resolve()
    if ROOT in out.parents:
        print("Çıktı depo içinde olamaz (gizli değerler Git'e girmesin).", file=sys.stderr)
        return 1
    if "/" in args.site or ":" in args.site:
        print("--site yalnız alan adı olmalı (https:// ve yol yok).", file=sys.stderr)
        return 1
    local = read_env(Path(args.source))
    postgres_password = secrets.token_urlsafe(32)
    runtime_password = secrets.token_urlsafe(32)
    lines = [
        "# Üretim ortamı (scripts/make_production_env.py ile üretildi). Git'e eklenmez.",
        f"SITE_ADDRESS={args.site}",
        "POSTGRES_DB=nhr_legal_ai",
        "POSTGRES_USER=nhr_app",
        f"POSTGRES_PASSWORD={postgres_password}",
        "NHR_RUNTIME_DB_USER=nhr_runtime",
        f"NHR_RUNTIME_DB_PASSWORD={runtime_password}",
        f"DATABASE_URL=postgresql://nhr_runtime:{runtime_password}@db:5432/nhr_legal_ai",
        f"DATABASE_ADMIN_URL=postgresql://nhr_app:{postgres_password}@db:5432/nhr_legal_ai",
        f"CORS_ORIGINS=https://{args.site}",
        f"WEB_BASE_URL=https://{args.site}",
        f"GOOGLE_REDIRECT_URI=https://{args.site}/api/auth/google/callback",
        f"GOOGLE_WEB_CALLBACK_URL=https://{args.site}/auth/callback",
        f"JWT_SECRET={secrets.token_urlsafe(48)}",
        "JWT_EXPIRE_MINUTES=480",
        "AUTH_COOKIE_SECURE=true",
        "ALLOW_REGISTRATION=false",
        "DOCUMENT_STORAGE_DIR=/data/uploads",
        "OLLAMA_BASE_URL=http://ollama:11434",
    ]
    missing = []
    for key in CARRY:
        if key in local and local[key] != "":
            lines.append(f"{key}={local[key]}")
        elif key in ("AI_PROVIDER", "CLOUD_AI_PROVIDER", "AWS_BEARER_TOKEN_BEDROCK"):
            missing.append(key)
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_STARTTLS"):
        if local.get(key):
            lines.append(f"{key}={local[key]}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Yazıldı: {out} ({len(lines)} satır). Gizli değerler dosyada; ekrana yazılmadı.")
    if missing:
        print("UYARI: yerel .env'de bulunamadı ->", ", ".join(missing), "(Bedrock cevapları çalışmaz; elle ekleyin)")
    print("Sonraki: dosyayı sunucuya /srv/nhr/.env.production olarak koyun, veritabanı parolalarını deploy/README.md'deki gibi değiştirin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
