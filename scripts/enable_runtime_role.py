"""Give `nhr_runtime` a login and point the application at it.

Table owners and superusers bypass row-level security, so policies only take
effect once the API stops connecting as the migration role. This script sets a
password on the unprivileged runtime role, rewrites `DATABASE_URL` in `.env`,
and verifies that RLS actually filters through the new connection.

    python scripts/enable_runtime_role.py
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
RUNTIME_ROLE = "nhr_runtime"
PLACEHOLDERS = {"", "change_me_runtime_local_only"}


def admin_url(values: dict[str, str | None]) -> str:
    explicit = values.get("DATABASE_ADMIN_URL")
    if explicit:
        return explicit
    missing = [
        name
        for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not values.get(name)
    ]
    if missing:
        raise SystemExit(
            "DATABASE_ADMIN_URL veya PostgreSQL değişkenleri eksik: " + ", ".join(missing)
        )
    user = quote(values["POSTGRES_USER"], safe="")
    password = quote(values["POSTGRES_PASSWORD"], safe="")
    database = quote(values["POSTGRES_DB"], safe="")
    port = values.get("POSTGRES_PORT") or "5433"
    return f"postgresql://{user}:{password}@localhost:{port}/{database}"


def runtime_url(admin: str, password: str) -> str:
    parts = urlsplit(admin)
    host = parts.hostname or "localhost"
    authority = f"{RUNTIME_ROLE}:{quote(password, safe='')}@{host}"
    if parts.port:
        authority = f"{authority}:{parts.port}"
    return urlunsplit((parts.scheme, authority, parts.path, parts.query, parts.fragment))


def rewrite_env(assignments: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    remaining = dict(assignments)
    for position, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[position] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if not ENV_PATH.exists():
        raise SystemExit(".env bulunamadı; önce .env.example dosyasını kopyalayın.")

    values = dotenv_values(ENV_PATH)
    existing = (values.get("NHR_RUNTIME_DB_PASSWORD") or "").strip()
    password = existing if existing not in PLACEHOLDERS else secrets.token_urlsafe(32)
    admin = admin_url(values)

    with psycopg.connect(admin, connect_timeout=5, autocommit=True) as connection:
        role_exists = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (RUNTIME_ROLE,)
        ).fetchone()[0]
        if not role_exists:
            raise SystemExit(
                f"{RUNTIME_ROLE} rolü yok; önce database/init/005_v2_hardening.sql uygulanmalı."
            )
        connection.execute(
            sql.SQL(
                "ALTER ROLE {role} LOGIN PASSWORD {password} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
            ).format(role=sql.Identifier(RUNTIME_ROLE), password=sql.Literal(password))
        )

    url = runtime_url(admin, password)
    with psycopg.connect(url, connect_timeout=5) as connection:
        current_user = connection.execute("SELECT current_user").fetchone()[0]
        # Without an app.user_id the policies must hide every user row; if this
        # returns anything, the connection is still bypassing RLS.
        visible_users = connection.execute("SELECT count(*) FROM users").fetchone()[0]

    if current_user != RUNTIME_ROLE:
        raise SystemExit(f"Beklenen rol {RUNTIME_ROLE}, bağlanılan rol {current_user}")
    if visible_users:
        raise SystemExit(
            f"RLS devrede değil: oturum bağlamı olmadan {visible_users} kullanıcı görülüyor."
        )

    rewrite_env(
        {
            "NHR_RUNTIME_DB_PASSWORD": password,
            "DATABASE_URL": url,
            # Migrations, corpus ingestion and the pre-authentication auth
            # queries stay on the owner role and need it spelled out.
            "DATABASE_ADMIN_URL": admin,
        }
    )
    print(f"{RUNTIME_ROLE} login açıldı, .env güncellendi ve RLS filtrelemesi doğrulandı.")
    print("API çalışıyorsa yeni bağlantıyı alması için yeniden başlatın.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
