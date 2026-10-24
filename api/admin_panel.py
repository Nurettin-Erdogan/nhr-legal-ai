"""Platform yönetici paneli: genel bakış, kullanıcılar, erişim (herkes / yalnız erişim listesi), geri bildirimler.

Güvenlik:
* Her uç `require_admin` ile korunur; sorgular yöneticinin kendi oturumuyla (`authenticated_database_connection`, RLS) çalışır.
* Yönetici avukatların müvekkil/dava/belge/sohbet İÇERİĞİNİ görmez: kullanıcı listesi ve özet yalnız sayı döndüren SECURITY
  DEFINER işlevlerden gelir (migration 062). Geri bildirim metni kullanıcının platform ekibine yazdığı mesajdır.
* Her değişiklik denetim kaydına yazılır (`admin.*`; e-posta yazılmaz). Yönetici kendini askıya alamaz, kendi
  yöneticiliğini kaldıramaz; yöneticiler erişim listesinde olmasa da girer.
* Askıya alınan, listeden çıkarılan ya da mod "yalnız liste"ye geçince erişimi kalmayan hesabın açık oturumları hemen
  kapatılır; erişim ayrıca her istekte denetlenir (api/access.py), kapatma yazılamasa da giremez.
* Kimlikler uygulamada üretilir; kullanıcı tablolarına `RETURNING id` yoktur.
* Uçlar yalnız GET/POST/DELETE kullanır: API'nin CORS listesi PUT/PATCH'e izin vermez, tarayıcı ön kontrolde reddeder.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field

from api.access import DEFAULT_MODE, MODES
from api.admin_ingestion import require_admin
from api.audit import AuditContext, record_event
from api.auth.routes import revoke_sessions, revoke_sessions_without_access
from api.config import get_settings
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-panel"])

ROLE_CODES = ("admin", "lawyer", "assistant", "viewer")
ROOT = Path(__file__).resolve().parents[1]


class UserRow(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None
    status: str
    created_at: datetime
    last_login_at: datetime | None
    roles: list[str]
    cases: int
    clients: int
    documents: int
    conversations: int
    ai_answers_30d: int
    last_activity_at: datetime | None
    listed: bool  # e-postası erişim listesinde
    has_access: bool  # şu an girebilir mi (aktif + mod/liste/yönetici)


class StatusChange(BaseModel):
    status: Literal["active", "suspended"]


class AccessModeChange(BaseModel):
    mode: Literal["open", "allowlist"]


class AccessEntryCreate(BaseModel):
    email: EmailStr
    note: str | None = Field(default=None, max_length=200)


def _db_error(exc: Exception, what: str) -> HTTPException:
    logger.exception("Yönetici paneli: %s", what)
    return HTTPException(status_code=503, detail=f"{what} şu anda okunamadı")


# --- Sistem durumu ---------------------------------------------------------------------------------------------------

_cloud_cache: tuple[float, dict] | None = None


def _cloud_budget() -> dict:
    """Bulut model bakiyesi (OpenRouter anahtarının limit/kullanımı); 2 dakika önbellekte, hata panelin geri kalanını bozmaz."""
    global _cloud_cache
    settings = get_settings()
    info: dict[str, Any] = {"provider": settings.cloud_ai_provider or None, "model": settings.cloud_ai_model or None}
    if settings.cloud_ai_provider != "openrouter" or not settings.cloud_ai_api_key:
        return info
    if _cloud_cache and monotonic() - _cloud_cache[0] < 120:
        return {**info, **_cloud_cache[1]}
    budget: dict[str, Any] = {}
    try:
        response = httpx.get("https://openrouter.ai/api/v1/key", timeout=4,
                             headers={"authorization": f"Bearer {settings.cloud_ai_api_key}"})
        data = response.json().get("data", {}) if response.status_code == 200 else {}
        budget = {"usage_usd": data.get("usage"), "limit_usd": data.get("limit"),
                  "remaining_usd": data.get("limit_remaining")}
    except (httpx.HTTPError, ValueError):
        budget = {"error": "bakiye okunamadı"}
    _cloud_cache = (monotonic(), budget)
    return {**info, **budget}


def _local_model() -> dict:
    settings = get_settings()
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=1.5, trust_env=False)
        names = [item.get("name") for item in response.json().get("models", [])] if response.status_code == 200 else []
        return {"reachable": response.status_code == 200, "model": settings.ai_model,
                "installed": settings.ai_model in names or f"{settings.ai_model}:latest" in names}
    except (httpx.HTTPError, ValueError):
        return {"reachable": False, "model": settings.ai_model, "installed": False}


def _last_backup() -> dict:
    """En yeni kullanıcı verisi yedeği (scripts/backup_user_data.py). Bildirimsiz duran gece yedeği 2026-10-24'te bulundu."""
    root = Path(os.environ.get("BACKUP_DIR", ROOT / "data" / "backups" / "user"))
    try:
        folders = sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("jurisai-")), reverse=True)
    except OSError:
        return {"found": False}
    for folder in folders:
        manifest = folder / "manifest.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            return {"found": True, "created_at": data.get("created_at"), "rows": sum((data.get("tables") or {}).values()),
                    "database_bytes": (data.get("dump") or {}).get("bytes"),
                    "uploads_included": "uploads" in data}
    return {"found": False}


def _corpus() -> dict:
    try:
        from api.legal import corpus_stats
        stats = corpus_stats()
        return {"decisions": stats.decision_count, "pending_verification": stats.seed_count,
                "legislation": stats.legislation_count,
                "latest_decision_date": stats.latest_decision_date, "embeddings": stats.embeddings}
    except Exception:  # noqa: BLE001 - korpus sayacı panelin geri kalanını bozmaz
        logger.exception("Yönetici paneli: korpus sayısı okunamadı")
        return {}


# --- Uçlar -----------------------------------------------------------------------------------------------------------

@router.get("/overview")
def overview(admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    try:
        with authenticated_database_connection(str(admin_id)) as connection:
            summary = connection.execute("SELECT * FROM admin_platform_summary()").fetchone()
    except psycopg.Error as exc:
        raise _db_error(exc, "Platform özeti") from exc
    return {"summary": dict(summary or {}), "health": {"database": True, "local_model": _local_model(),
            "cloud": _cloud_budget(), "backup": _last_backup()}, "corpus": _corpus()}


@router.get("/users", response_model=list[UserRow])
def users(
    admin_id: Annotated[UUID, Depends(require_admin)],
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: Literal["active", "inactive", "suspended"] | None = None,
) -> list[UserRow]:
    try:
        with authenticated_database_connection(str(admin_id)) as connection:
            rows = connection.execute("SELECT * FROM admin_user_overview()").fetchall()
    except psycopg.Error as exc:
        raise _db_error(exc, "Kullanıcı listesi") from exc
    needle = (q or "").strip().casefold()
    result = []
    for row in rows:
        if status and row["status"] != status:
            continue
        if needle and needle not in f"{row['email']} {row['full_name'] or ''}".casefold():
            continue
        result.append(UserRow(**row))
    return result


@router.post("/users/{user_id}/status")
def change_status(user_id: UUID, change: StatusChange, request: Request,
                  admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    if user_id == admin_id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızın durumunu değiştiremezsiniz")
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            row = connection.execute("SELECT status FROM users WHERE id = %s AND deleted_at IS NULL",
                                     (user_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
            connection.execute("UPDATE users SET status = %s WHERE id = %s", (change.status, user_id))
            record_event(connection, action="admin.user_status", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), entity_type="user", entity_id=user_id,
                         metadata={"from": row["status"], "to": change.status})
    except psycopg.Error as exc:
        raise _db_error(exc, "Kullanıcı durumu") from exc
    if change.status == "suspended":
        revoke_sessions(user_id)  # açık oturumlar hemen kapanır
    return {"user_id": str(user_id), "status": change.status}


@router.post("/users/{user_id}/roles/{role}")
def grant_role(user_id: UUID, role: Literal["admin", "lawyer", "assistant", "viewer"], request: Request,
               admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            if not connection.execute("SELECT 1 FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")
            connection.execute(
                "INSERT INTO user_roles (user_id, role_id, granted_by) SELECT %s, id, %s FROM roles WHERE code = %s "
                "ON CONFLICT (user_id, role_id) DO NOTHING", (user_id, admin_id, role))
            record_event(connection, action="admin.role_grant", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), entity_type="user", entity_id=user_id,
                         metadata={"role": role})
    except psycopg.Error as exc:
        raise _db_error(exc, "Rol") from exc
    return {"user_id": str(user_id), "role": role, "granted": True}


@router.delete("/users/{user_id}/roles/{role}")
def revoke_role(user_id: UUID, role: Literal["admin", "lawyer", "assistant", "viewer"], request: Request,
                admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    if user_id == admin_id and role == "admin":
        raise HTTPException(status_code=400, detail="Kendi yöneticilik yetkinizi kaldıramazsınız")
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            connection.execute(
                "DELETE FROM user_roles WHERE user_id = %s AND role_id = (SELECT id FROM roles WHERE code = %s)",
                (user_id, role))
            record_event(connection, action="admin.role_revoke", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), entity_type="user", entity_id=user_id,
                         metadata={"role": role})
    except psycopg.Error as exc:
        raise _db_error(exc, "Rol") from exc
    return {"user_id": str(user_id), "role": role, "granted": False}


@router.get("/feedback")
def feedback(
    admin_id: Annotated[UUID, Depends(require_admin)],
    category: Literal["hata", "oneri", "begeni"] | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[dict]:
    try:
        with authenticated_database_connection(str(admin_id)) as connection:
            rows = connection.execute("SELECT * FROM admin_feedback_list(%s, %s)", (limit, category)).fetchall()
    except psycopg.Error as exc:
        raise _db_error(exc, "Geri bildirimler") from exc
    return [dict(row) for row in rows]


@router.get("/access")
def access(admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    try:
        with authenticated_database_connection(str(admin_id)) as connection:
            mode = connection.execute("SELECT value FROM platform_settings WHERE key = 'access_mode'").fetchone()
            entries = connection.execute(
                """
                SELECT a.id, a.email, a.note, a.added_at, u.status AS account_status
                FROM access_allowlist a
                LEFT JOIN users u ON lower(u.email) = a.email AND u.deleted_at IS NULL
                ORDER BY a.added_at DESC
                LIMIT 1000
                """).fetchall()
            # "Yalnız listedekiler" seçiliyse (ya da seçilirse) giremeyecek aktif hesaplar; yöneticiler her zaman girer.
            unlisted = connection.execute(
                "SELECT count(*) AS n FROM admin_user_overview() "
                "WHERE status = 'active' AND NOT listed AND NOT ('admin' = ANY(roles))").fetchone()
    except psycopg.Error as exc:
        raise _db_error(exc, "Erişim ayarı") from exc
    return {"mode": (mode or {}).get("value", DEFAULT_MODE), "modes": list(MODES),
            "registration_allowed": get_settings().allow_registration,
            "unlisted_accounts": int((unlisted or {}).get("n") or 0), "entries": [dict(row) for row in entries]}


@router.post("/access")
def set_access_mode(change: AccessModeChange, request: Request,
                    admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            connection.execute(
                "INSERT INTO platform_settings (key, value, updated_by, updated_at) "
                "VALUES ('access_mode', %s, %s, now()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                "updated_at = now()", (change.mode, admin_id))
            record_event(connection, action="admin.access_mode", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), metadata={"mode": change.mode})
    except psycopg.Error as exc:
        raise _db_error(exc, "Erişim ayarı") from exc
    return {"mode": change.mode, "closed_sessions": _close_sessions_without_access() if change.mode == "allowlist" else 0}


@router.post("/access/entries", status_code=201)
def add_access(entry: AccessEntryCreate, request: Request, admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    email = str(entry.email).strip().lower()
    entry_id = uuid4()
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            connection.execute(
                "INSERT INTO access_allowlist (id, email, note, added_by) VALUES (%s, %s, %s, %s)",
                (entry_id, email, (entry.note or "").strip() or None, admin_id))
            # E-posta günlüğe yazılmaz; satırın kimliği yeterli.
            record_event(connection, action="admin.access_add", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), entity_type="access_entry", entity_id=entry_id)
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Bu e-posta zaten erişim listesinde") from exc
    except psycopg.Error as exc:
        raise _db_error(exc, "Erişim listesi") from exc
    return {"id": str(entry_id), "email": email}


@router.delete("/access/entries/{entry_id}")
def remove_access(entry_id: UUID, request: Request, admin_id: Annotated[UUID, Depends(require_admin)]) -> dict:
    try:
        with authenticated_database_connection(str(admin_id)) as connection, connection.transaction():
            row = connection.execute("SELECT email FROM access_allowlist WHERE id = %s", (entry_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Bu kayıt erişim listesinde yok")
            connection.execute("DELETE FROM access_allowlist WHERE id = %s", (entry_id,))
            affected = [user["id"] for user in connection.execute(
                "SELECT id FROM users WHERE lower(email) = %s AND deleted_at IS NULL", (row["email"],)).fetchall()]
            record_event(connection, action="admin.access_remove", actor_user_id=admin_id,
                         context=AuditContext.from_request(request), entity_type="access_entry", entity_id=entry_id)
    except psycopg.Error as exc:
        raise _db_error(exc, "Erişim listesi") from exc
    # Hesabı varsa ve artık giremiyorsa (yönetici değil, mod "yalnız liste") açık oturumu hemen kapanır.
    return {"id": str(entry_id), "removed": True,
            "closed_sessions": _close_sessions_without_access(affected) if affected else 0}


def _close_sessions_without_access(user_ids: list[UUID] | None = None) -> int:
    try:
        return revoke_sessions_without_access(user_ids)
    except (psycopg.Error, RuntimeError):
        # Erişim zaten her istekte denetlenir (5 sn önbellek); toplu kapatma yazılamasa da listede olmayan giremez.
        logger.exception("Erişimi kalmayan oturumlar kapatılamadı")
        return 0
