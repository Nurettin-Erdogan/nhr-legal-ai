"""Hesap işlemleri: profil, parola değiştirme, şifre sıfırlama ve hesabın silinmesi (KVKK).

Bu modül kimlik bilgilerine dokunduğu için yönetici bağlantısıyla (`nhr_app`) çalışır; her işlem önce oturum sahibini doğrular ve
yalnız onun satırlarına dokunur. Denetim kaydına e-posta, ad ya da parola yazılmaz; yalnız olayın türü ve hesabın kimliği.

* **Parola değiştirme** mevcut parolayı ister (Google ile açılıp parolası olmayan hesap hariç), ardından diğer bütün oturumları
  kapatır ve bu oturuma yeni jeton verir.
* **Şifre sıfırlama** tek kullanımlık, 60 dakika geçerli bir bağlantıyla yapılır. Anahtarın yalnız SHA-256 özeti saklanır. İstek
  yanıtı hesabın var olup olmadığını ele vermez. E-posta (SMTP) yapılandırılmamışsa bağlantı e-postayla gönderilemez; bu durumda
  arayüz bunu açıkça söyler ve bağlantıyı yönetici `scripts/create_password_reset_link.py` ile üretir.
* **Hesap silme** kullanıcının bütün verisini (müvekkil, dava, görev, takvim, belge ve dosyaları, sohbetler, yapay zekâ çıktıları,
  bağlantı anahtarları) kalıcı olarak siler ve hesap satırını anonimleştirir (e-posta, ad ve parola silinir). Hesap satırı,
  denetim kayıtlarındaki kimliksiz iz için kalır; kişisel veri içermez ve o e-postayla yeniden kayıt olunabilir.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from api import mailer
from api.audit import AuditContext, email_fingerprint, record_event, record_event_standalone
from api.auth import routes as auth_routes
from api.auth.schemas import AuthResponse, UserResponse
from api.auth.security import hash_password, verify_password
from api.config import get_settings
from api.db import admin_database_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["account"])

PASSWORD_CHANGE = "auth.password_change"
PASSWORD_CHANGE_FAILED = "auth.password_change_failed"
PASSWORD_RESET_REQUEST = "auth.password_reset_request"
PASSWORD_RESET = "auth.password_reset"
PASSWORD_RESET_FAILED = "auth.password_reset_failed"
ACCOUNT_DELETE = "account.delete"
PROFILE_UPDATE = "account.profile_update"

RESET_TOKEN_MINUTES = 60
THROTTLE_WINDOW_MINUTES = 15
MAX_FAILURES = 8
MAX_RESET_REQUESTS_PER_IP = 10
DELETE_PHRASE = "HESABIMI SİL"

# `owner_id` taşıyan büro tabloları: hesap silinirken hepsi temizlenir. Liste veritabanından okunur (yeni tablo unutulmasın);
# bu sabit yalnız veritabanı okunamadığında kullanılan güvenli alt kümedir.
_OWNER_TABLES_SQL = """
SELECT table_name FROM information_schema.columns
WHERE table_schema = 'public' AND column_name = 'owner_id' AND table_name LIKE 'office\\_%'
ORDER BY table_name
"""


def _web_base_url() -> str:
    explicit = os.getenv("WEB_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    origins = get_settings().cors_origins
    return (origins[0] if origins else "http://localhost:3000").rstrip("/")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _recent_events(connection, action: str, *, actor: UUID | None = None, ip: str | None = None) -> int:
    row = connection.execute(
        "SELECT count(*) AS n FROM activity_logs WHERE action = %s AND created_at > now() - make_interval(mins => %s) "
        "AND (%s::uuid IS NULL OR actor_user_id = %s::uuid) AND (%s::inet IS NULL OR ip_address = %s::inet)",
        (action, THROTTLE_WINDOW_MINUTES, actor, actor, ip, ip),
    ).fetchone()
    return int(row["n"])


def _too_many(detail: str = "Çok fazla deneme yapıldı.") -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"{detail} {THROTTLE_WINDOW_MINUTES} dakika sonra tekrar deneyin.",
        headers={"Retry-After": str(THROTTLE_WINDOW_MINUTES * 60)},
    )


# --- Profil --------------------------------------------------------------------------------------------------------------


class ProfileRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)


@router.post("/api/account/profile", response_model=UserResponse)
def update_profile(
    body: ProfileRequest, http_request: Request, user_id: Annotated[UUID, Depends(auth_routes.current_user_id)]
) -> UserResponse:
    try:
        with admin_database_connection() as connection, connection.transaction():
            connection.execute("UPDATE users SET full_name = %s WHERE id = %s AND deleted_at IS NULL", (" ".join(body.full_name.split()), user_id))
            row = connection.execute(auth_routes._USER_SELECT.format(field="id"), (user_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail="Oturum kullanıcısı bulunamadı")
            record_event(connection, action=PROFILE_UPDATE, actor_user_id=user_id, context=AuditContext.from_request(http_request),
                         entity_type="user", entity_id=user_id, strict=False)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Profil güncellenemedi") from exc
    return auth_routes._as_user(row)


# --- Parola değiştirme ---------------------------------------------------------------------------------------------------


class PasswordChangeRequest(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


@router.get("/api/account/security")
def account_security(user_id: Annotated[UUID, Depends(auth_routes.current_user_id)]) -> dict[str, bool]:
    """Arayüzün doğru formu göstermesi için: hesabın parolası var mı (Google ile açılan hesapta olmayabilir)."""
    try:
        with admin_database_connection() as connection:
            row = connection.execute("SELECT password_hash IS NOT NULL AS has_password FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)).fetchone()
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Hesap bilgisi okunamadı") from exc
    if row is None:
        raise HTTPException(status_code=401, detail="Oturum kullanıcısı bulunamadı")
    return {"has_password": bool(row["has_password"]), "email_delivery": mailer.is_configured()}


def _verify_current_password(connection, user_id: UUID, supplied: str | None, context: AuditContext) -> dict:
    """Mevcut parolayı doğrular; hesabın parolası yoksa (Google) doğrulama istenmez. Başarısızlık sayılır ve sınırlanır."""
    row = connection.execute("SELECT id, email, password_hash FROM users WHERE id = %s AND deleted_at IS NULL AND status = 'active'", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Oturum kullanıcısı bulunamadı")
    if row["password_hash"] is None:
        return row
    if _recent_events(connection, PASSWORD_CHANGE_FAILED, actor=user_id) >= MAX_FAILURES:
        raise _too_many()
    if not supplied or not verify_password(supplied, row["password_hash"]):
        raise PermissionError
    return row


@router.post("/api/account/password", response_model=AuthResponse)
def change_password(
    body: PasswordChangeRequest, response: Response, http_request: Request,
    user_id: Annotated[UUID, Depends(auth_routes.current_user_id)],
) -> AuthResponse:
    context = AuditContext.from_request(http_request)
    try:
        with admin_database_connection() as connection, connection.transaction():
            try:
                _verify_current_password(connection, user_id, body.current_password, context)
            except PermissionError:
                failed = True
            else:
                failed = False
                connection.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(body.new_password), user_id))
                connection.execute("UPDATE auth_password_resets SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user_id,))
                record_event(connection, action=PASSWORD_CHANGE, actor_user_id=user_id, context=context, entity_type="user", entity_id=user_id, strict=False)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Parola değiştirilemedi") from exc
    if failed:
        record_event_standalone(action=PASSWORD_CHANGE_FAILED, actor_user_id=user_id, context=context, entity_type="user", entity_id=user_id)
        raise HTTPException(status_code=403, detail="Mevcut parola hatalı")
    # Diğer cihazlardaki oturumlar kapanır; bu oturuma iptal anından sonra verilmiş yeni jeton yazılır.
    try:
        auth_routes.revoke_sessions(user_id)
        with admin_database_connection() as connection:
            row = connection.execute(auth_routes._USER_SELECT.format(field="id"), (user_id,)).fetchone()
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Parola değişti ama oturum yenilenemedi; yeniden giriş yapın") from exc
    return auth_routes._issue_auth_response(response, row)


# --- Şifre sıfırlama -----------------------------------------------------------------------------------------------------


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)


def create_reset_token(connection, user_id: UUID) -> str:
    """Kullanıcı için tek kullanımlık sıfırlama anahtarı üretir (özeti saklanır) ve önceki açık anahtarları geçersiz kılar."""
    token = secrets.token_urlsafe(32)
    connection.execute("UPDATE auth_password_resets SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user_id,))
    connection.execute(
        "INSERT INTO auth_password_resets (id, user_id, token_hash, expires_at) VALUES (%s, %s, %s, %s)",
        (uuid4(), user_id, token_digest(token), datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_MINUTES)),
    )
    return token


def reset_link(token: str) -> str:
    return f"{_web_base_url()}/sifre-sifirla?token={token}"


@router.get("/api/auth/password-reset/status")
def reset_status() -> dict[str, bool]:
    return {"email_delivery": mailer.is_configured()}


@router.post("/api/auth/password-reset/request")
def request_reset(body: ResetRequest, http_request: Request) -> dict[str, object]:
    """Yanıt hesabın var olup olmadığını ele vermez. `delivery`: sunucunun e-posta gönderip gönderemediği (hesaptan bağımsız)."""
    context = AuditContext.from_request(http_request)
    email = str(body.email).strip().lower()
    delivery = "email" if mailer.is_configured() else "manual"
    link: str | None = None
    try:
        with admin_database_connection() as connection, connection.transaction():
            if _recent_events(connection, PASSWORD_RESET_REQUEST, ip=context.ip_address) >= MAX_RESET_REQUESTS_PER_IP:
                raise _too_many("Çok fazla sıfırlama isteği gönderildi.")
            record_event(connection, action=PASSWORD_RESET_REQUEST, actor_user_id=None, context=context,
                         metadata={"email_fingerprint": email_fingerprint(email), "delivery": delivery}, strict=False)
            if delivery == "email":
                row = connection.execute(
                    "SELECT id FROM users WHERE email = %s AND deleted_at IS NULL AND status = 'active'", (email,)
                ).fetchone()
                if row is not None:
                    link = reset_link(create_reset_token(connection, row["id"]))
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Sıfırlama isteği alınamadı") from exc
    if link is not None:
        try:
            mailer.send_mail(
                email,
                "JurisAI şifre sıfırlama",
                "JurisAI hesabınız için şifre sıfırlama isteği aldık.\n\n"
                f"Yeni şifrenizi belirlemek için {RESET_TOKEN_MINUTES} dakika içinde şu bağlantıyı açın:\n{link}\n\n"
                "Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz; şifreniz değişmez.",
            )
        except mailer.MailError:
            logger.warning("Şifre sıfırlama e-postası gönderilemedi")
    return {"ok": True, "delivery": delivery}


@router.post("/api/auth/password-reset/confirm", status_code=204)
def confirm_reset(body: ResetConfirm, http_request: Request) -> Response:
    context = AuditContext.from_request(http_request)
    user_id: UUID | None = None
    try:
        with admin_database_connection() as connection, connection.transaction():
            if _recent_events(connection, PASSWORD_RESET_FAILED, ip=context.ip_address) >= MAX_FAILURES:
                raise _too_many()
            row = connection.execute(
                "SELECT r.id, r.user_id FROM auth_password_resets r JOIN users u ON u.id = r.user_id "
                "WHERE r.token_hash = %s AND r.used_at IS NULL AND r.expires_at > now() "
                "AND u.deleted_at IS NULL AND u.status = 'active' FOR UPDATE OF r",
                (token_digest(body.token),),
            ).fetchone()
            if row is not None:
                user_id = row["user_id"]
                connection.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(body.new_password), user_id))
                connection.execute("UPDATE auth_password_resets SET used_at = now() WHERE user_id = %s AND used_at IS NULL", (user_id,))
                record_event(connection, action=PASSWORD_RESET, actor_user_id=user_id, context=context, entity_type="user", entity_id=user_id, strict=False)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Şifre sıfırlanamadı") from exc
    if user_id is None:
        record_event_standalone(action=PASSWORD_RESET_FAILED, context=context)
        raise HTTPException(status_code=400, detail="Sıfırlama bağlantısı geçersiz ya da süresi dolmuş. Yeni bağlantı isteyin.")
    try:
        auth_routes.revoke_sessions(user_id)  # eski parola ile açılmış bütün oturumlar kapanır
    except (psycopg.Error, RuntimeError):
        logger.exception("Sıfırlama sonrası oturum iptali yazılamadı")
    return Response(status_code=204)


# --- Hesabı silme (KVKK) -------------------------------------------------------------------------------------------------


class DeleteRequest(BaseModel):
    password: str | None = Field(default=None, max_length=128)
    confirm: str = Field(max_length=40)


def purge_user_data(connection, user_id: UUID) -> dict[str, int]:
    """Kullanıcının bütün verisini siler ve hesap satırını anonimleştirir. Çağıran işlemi (transaction) açmış olmalıdır.

    Dosyalar burada silinmez (veritabanı işlemi geri alınabilir, disk silme alınamaz): çağıran işlem bittikten sonra
    `remove_user_files` çağırır. Dönüş: tablo başına silinen satır sayısı (denetim ve test için; içerik yok).
    """
    counts: dict[str, int] = {}
    connection.execute("SELECT set_config('app.allow_user_data_purge', 'on', true)")
    # Sıra: atıflar (sohbetler) → belge parçaları → büro kayıtları. `citations.document_chunk_id` belgeyi silmeyi engeller.
    counts["conversations"] = connection.execute("DELETE FROM conversations WHERE created_by = %s", (user_id,)).rowcount
    counts["documents"] = connection.execute("DELETE FROM documents WHERE uploaded_by = %s", (user_id,)).rowcount
    tables = [row["table_name"] for row in connection.execute(_OWNER_TABLES_SQL).fetchall()]
    for table in tables:
        counts[table] = connection.execute(
            sql.SQL("DELETE FROM {} WHERE owner_id = %s").format(sql.Identifier(table)), (user_id,)
        ).rowcount
    counts["projects"] = connection.execute("DELETE FROM projects WHERE created_by = %s", (user_id,)).rowcount
    counts["clients"] = connection.execute("DELETE FROM clients WHERE created_by = %s", (user_id,)).rowcount
    for table, column in (("saved_legal_sources", "user_id"), ("project_members", "user_id"), ("auth_google_identities", "user_id"),
                          ("auth_password_resets", "user_id"), ("user_roles", "user_id")):
        counts[table] = connection.execute(
            sql.SQL("DELETE FROM {} WHERE {} = %s").format(sql.Identifier(table), sql.Identifier(column)), (user_id,)
        ).rowcount
    # Hesap satırı anonimleşir: kişisel veri kalmaz, e-posta yeniden kullanılabilir, oturumlar kapanır.
    connection.execute(
        "UPDATE users SET email = %s, full_name = NULL, password_hash = NULL, status = 'inactive', deleted_at = now(), "
        "deleted_by = id, sessions_valid_after = now() WHERE id = %s",
        (f"silindi-{uuid4().hex}@deleted.invalid", user_id),
    )
    return counts


def remove_user_files(user_id: UUID) -> bool:
    """Kullanıcının diskteki belge klasörünü siler. Klasör yoksa True; silinemezse False (günlüğe yazılır)."""
    root = (Path(get_settings().document_storage_dir) / "office").resolve()
    target = (root / str(user_id)).resolve()
    if root not in target.parents:  # yol güvenliği: yalnız depolama kökünün altındaki klasör silinir
        return False
    if not target.exists():
        return True
    shutil.rmtree(target, ignore_errors=True)
    if target.exists():
        logger.error("Silinen hesabın dosya klasörü kaldırılamadı id=%s", user_id)
        return False
    return True


@router.post("/api/account/delete", status_code=204)
def delete_account(
    body: DeleteRequest, http_request: Request, user_id: Annotated[UUID, Depends(auth_routes.current_user_id)]
) -> Response:
    if body.confirm.strip() != DELETE_PHRASE:
        raise HTTPException(status_code=400, detail=f'Onay için "{DELETE_PHRASE}" yazın.')
    context = AuditContext.from_request(http_request)
    failed = False
    try:
        with admin_database_connection() as connection, connection.transaction():
            try:
                _verify_current_password(connection, user_id, body.password, context)
            except PermissionError:
                failed = True
            else:
                counts = purge_user_data(connection, user_id)
                record_event(connection, action=ACCOUNT_DELETE, actor_user_id=user_id, context=context, entity_type="user", entity_id=user_id,
                             metadata={"rows": sum(counts.values())}, strict=False)
    except (psycopg.Error, RuntimeError) as exc:
        logger.exception("Hesap silinemedi id=%s", user_id)
        raise HTTPException(status_code=503, detail="Hesap silinemedi; hiçbir veri silinmedi. Daha sonra tekrar deneyin.") from exc
    if failed:
        record_event_standalone(action=PASSWORD_CHANGE_FAILED, actor_user_id=user_id, context=context, entity_type="user", entity_id=user_id)
        raise HTTPException(status_code=403, detail="Parola hatalı")
    auth_routes._sessions_valid_after_cache.pop(user_id, None)
    remove_user_files(user_id)
    response = Response(status_code=204)
    response.delete_cookie(auth_routes.COOKIE_NAME, path="/")
    return response
