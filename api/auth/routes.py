from __future__ import annotations

from datetime import datetime, timedelta, timezone
import secrets
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID, uuid4

import jwt
import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation

from api.audit import (
    AUTH_LOGIN,
    AUTH_LOGIN_FAILED,
    AUTH_LOGOUT,
    AUTH_REGISTER,
    AuditContext,
    email_fingerprint,
    record_event,
    record_event_standalone,
)
from api.auth.schemas import (
    AuthResponse,
    AuthStatusResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from api.auth.google_oauth import (
    FLOW_COOKIE,
    FLOW_COOKIE_PATH,
    GoogleAccountExists,
    GoogleOAuthError,
    authorization_url,
    exchange_code,
    google_settings,
    new_flow,
    verify_identity,
)
from api.auth.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from api.config import get_settings
from api.db import admin_database_connection

router = APIRouter(prefix="/api/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)
COOKIE_NAME = "nhr_access_token"
GOOGLE_FLOW_SECONDS = 600

_USER_SELECT = """
SELECT
    users.id,
    users.email,
    users.full_name,
    users.status,
    users.created_at,
    users.password_hash,
    COALESCE(
        array_agg(roles.code ORDER BY roles.code) FILTER (WHERE roles.code IS NOT NULL),
        ARRAY[]::text[]
    ) AS roles
FROM users
LEFT JOIN user_roles ON user_roles.user_id = users.id
LEFT JOIN roles ON roles.id = user_roles.role_id
WHERE users.{field} = %s AND users.deleted_at IS NULL
GROUP BY users.id
"""


def _auth_secret() -> str:
    secret = get_settings().jwt_secret
    if not secret or len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT_SECRET en az 32 karakter olacak şekilde tanımlanmalı",
        )
    return secret


def _as_user(row: dict) -> UserResponse:
    return UserResponse(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        status=row["status"],
        roles=row["roles"],
        created_at=row["created_at"],
    )


def _set_auth_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _issue_auth_response(response: Response, row: dict) -> AuthResponse:
    settings = get_settings()
    token, expires_in = create_access_token(
        user_id=row["id"],
        secret=_auth_secret(),
        expires_minutes=settings.jwt_expire_minutes,
    )
    _set_auth_cookie(response, token, expires_in)
    return AuthResponse(
        access_token=token,
        expires_in=expires_in,
        user=_as_user(row),
    )


def current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    cookie_token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> UUID:
    token = credentials.credentials if credentials else cookie_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Oturum açılması gerekiyor",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(token, secret=_auth_secret())
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def optional_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    cookie_token: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> UUID | None:
    """Resolve the caller when a session exists, without demanding one."""
    token = credentials.credentials if credentials else cookie_token
    if not token:
        return None
    try:
        return decode_access_token(token, secret=_auth_secret())
    except TokenError:
        return None


@router.get("/status", response_model=AuthStatusResponse)
def auth_status() -> AuthStatusResponse:
    settings = get_settings()
    return AuthStatusResponse(
        configured=bool(settings.jwt_secret and len(settings.jwt_secret) >= 32),
        registration_enabled=settings.allow_registration,
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(
    request: RegisterRequest, response: Response, http_request: Request
) -> AuthResponse:
    settings = get_settings()
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="Yeni kullanıcı kaydı kapalı")
    _auth_secret()

    email = str(request.email).strip().lower()
    try:
        with admin_database_connection() as connection, connection.transaction():
            row = connection.execute(
                """
                INSERT INTO users (email, password_hash, full_name)
                VALUES (%s, %s, %s)
                RETURNING id, email, full_name, status, created_at,
                          password_hash, ARRAY[]::text[] AS roles
                """,
                (email, hash_password(request.password), request.full_name.strip()),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                SELECT %s, id FROM roles WHERE code = 'lawyer'
                """,
                (row["id"],),
            )
            row["roles"] = ["lawyer"]
            # E-posta ve ad günlüğe yazılmaz; yalnız yeni hesabın kimliği.
            record_event(
                connection,
                action=AUTH_REGISTER,
                actor_user_id=row["id"],
                context=AuditContext.from_request(http_request),
                entity_type="user",
                entity_id=row["id"],
                strict=False,
            )
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı") from exc
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Kullanıcı kaydı oluşturulamadı") from exc

    return _issue_auth_response(response, row)


@router.post("/login", response_model=AuthResponse)
def login(
    request: LoginRequest, response: Response, http_request: Request
) -> AuthResponse:
    _auth_secret()
    email = str(request.email).strip().lower()
    context = AuditContext.from_request(http_request)
    failure: str | None = None
    try:
        with admin_database_connection() as connection, connection.transaction():
            row = connection.execute(
                _USER_SELECT.format(field="email"), (email,)
            ).fetchone()
            valid = verify_password(request.password, row["password_hash"] if row else None)
            if not row or not valid or row["status"] != "active":
                # Hata fırlatmak transaction'ı geri alacağından başarısızlık burada yalnız
                # işaretlenir; kayıt ve 401 transaction bittikten sonra yapılır.
                failure = "account_inactive" if row and valid else "invalid_credentials"
            else:
                connection.execute(
                    "UPDATE users SET last_login_at = NOW() WHERE id = %s", (row["id"],)
                )
                record_event(
                    connection,
                    action=AUTH_LOGIN,
                    actor_user_id=row["id"],
                    context=context,
                    entity_type="user",
                    entity_id=row["id"],
                    strict=False,
                )
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Oturum açılamadı") from exc

    if failure is not None:
        # Kim olduğu doğrulanamadığından aktör boş kalır; e-posta düz yazılmaz.
        record_event_standalone(
            action=AUTH_LOGIN_FAILED,
            context=context,
            metadata={"reason": failure, "email_fingerprint": email_fingerprint(email)},
        )
        # Hesap yok / parola yanlış / hesap pasif aynı yanıtı verir (kullanıcı sayımı yapılamaz).
        raise HTTPException(status_code=401, detail="E-posta veya parola hatalı")

    return _issue_auth_response(response, row)


@router.get("/me", response_model=UserResponse)
def me(user_id: Annotated[UUID, Depends(current_user_id)]) -> UserResponse:
    try:
        with admin_database_connection() as connection:
            row = connection.execute(
                _USER_SELECT.format(field="id"), (user_id,)
            ).fetchone()
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Kullanıcı bilgisi alınamadı") from exc
    if not row or row["status"] != "active":
        raise HTTPException(status_code=401, detail="Oturum kullanıcısı bulunamadı")
    return _as_user(row)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    http_request: Request,
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
) -> Response:
    if user_id is not None:
        record_event_standalone(
            action=AUTH_LOGOUT,
            actor_user_id=user_id,
            context=AuditContext.from_request(http_request),
            entity_type="user",
            entity_id=user_id,
        )
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/google/status")
def google_status() -> dict[str, bool]:
    secret = get_settings().jwt_secret
    if not google_settings().configured or not secret or len(secret) < 32:
        return {"configured": False}
    try:
        with admin_database_connection() as connection:
            row = connection.execute(
                "SELECT to_regclass('public.auth_google_identities') IS NOT NULL AS ready"
            ).fetchone()
    except (psycopg.Error, RuntimeError):
        return {"configured": False}
    return {"configured": bool(row and row["ready"])}


@router.get("/google/connection")
def google_connection(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, bool]:
    try:
        with admin_database_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM auth_google_identities WHERE user_id = %s", (user_id,)
            ).fetchone()
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Google bağlantısı kontrol edilemedi") from exc
    return {"linked": bool(row)}


@router.get("/google/start")
def google_start(
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    link: bool = False,
) -> RedirectResponse:
    settings = google_settings()
    if not settings.configured:
        raise HTTPException(status_code=503, detail="Google ile giriş henüz yapılandırılmadı")
    if link and user_id is None:
        raise HTTPException(status_code=401, detail="Bağlamak için önce oturum açın")
    state, nonce, verifier = new_flow()
    now = datetime.now(timezone.utc)
    flow = jwt.encode(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "link_user_id": str(user_id) if link else None,
            "iat": now,
            "exp": now + timedelta(seconds=GOOGLE_FLOW_SECONDS),
        },
        _auth_secret(),
        algorithm="HS256",
    )
    response = RedirectResponse(
        authorization_url(settings, state=state, nonce=nonce, verifier=verifier),
        status_code=303,
    )
    response.set_cookie(
        FLOW_COOKIE,
        flow,
        max_age=GOOGLE_FLOW_SECONDS,
        httponly=True,
        secure=get_settings().auth_cookie_secure,
        samesite="lax",
        path=FLOW_COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _google_result_redirect(error: str | None = None, *, linked: bool = False) -> RedirectResponse:
    target = google_settings().web_callback_url
    suffix = "?" + urlencode({"error": error} if error else {"linked": "1"}) if error or linked else ""
    response = RedirectResponse(target + suffix, status_code=303)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"
    return response


def _google_user(subject: str, email: str, name: str, *, link_user_id: UUID | None, context: AuditContext) -> dict:
    """Link explicitly or provision a new account; never auto-link by email."""
    try:
        with admin_database_connection() as connection, connection.transaction():
            linked = connection.execute(
                "SELECT user_id FROM auth_google_identities WHERE google_subject = %s",
                (subject,),
            ).fetchone()
            if link_user_id:
                row = connection.execute(
                    _USER_SELECT.format(field="id"), (link_user_id,)
                ).fetchone()
                if not row or row["status"] != "active" or row["email"].lower() != email:
                    raise GoogleOAuthError("The accounts cannot be linked")
                if linked and linked["user_id"] != link_user_id:
                    raise GoogleOAuthError("Google account is already linked")
                if not linked:
                    connection.execute(
                        "INSERT INTO auth_google_identities (user_id, google_subject) VALUES (%s, %s)",
                        (link_user_id, subject),
                    )
                record_event(
                    connection, action="auth.google_link", actor_user_id=link_user_id,
                    context=context, entity_type="user", entity_id=link_user_id, strict=False,
                )
                return row
            if linked:
                row = connection.execute(
                    _USER_SELECT.format(field="id"), (linked["user_id"],)
                ).fetchone()
                if not row or row["status"] != "active":
                    raise GoogleOAuthError("Linked account is unavailable")
            else:
                if not get_settings().allow_registration:
                    raise GoogleOAuthError("Registration disabled")
                existing = connection.execute(
                    "SELECT 1 FROM users WHERE lower(email) = %s AND deleted_at IS NULL", (email,)
                ).fetchone()
                if existing:
                    raise GoogleAccountExists("Existing account needs explicit linking")
                user_id = uuid4()
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, NULL, %s)",
                    (user_id, email, name or None),
                )
                connection.execute(
                    "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE code = 'lawyer'",
                    (user_id,),
                )
                connection.execute(
                    "INSERT INTO auth_google_identities (user_id, google_subject) VALUES (%s, %s)",
                    (user_id, subject),
                )
                row = connection.execute(
                    _USER_SELECT.format(field="id"), (user_id,)
                ).fetchone()
                record_event(
                    connection, action=AUTH_REGISTER, actor_user_id=user_id,
                    context=context, entity_type="user", entity_id=user_id,
                    metadata={"method": "google"}, strict=False,
                )
            connection.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (row["id"],))
            record_event(
                connection, action=AUTH_LOGIN, actor_user_id=row["id"],
                context=context, entity_type="user", entity_id=row["id"],
                metadata={"method": "google"}, strict=False,
            )
            return row
    except UniqueViolation as exc:
        raise GoogleAccountExists("Existing account needs explicit linking") from exc
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Google hesabı kaydedilemedi") from exc


@router.get("/google/callback")
def google_callback(
    request: Request,
    user_id: Annotated[UUID | None, Depends(optional_current_user_id)],
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    flow_cookie: Annotated[str | None, Cookie(alias=FLOW_COOKIE)] = None,
) -> RedirectResponse:
    settings = google_settings()
    if not settings.configured or not flow_cookie or not state:
        raise HTTPException(status_code=400, detail="Google oturum isteği geçersiz")
    try:
        flow = jwt.decode(
            flow_cookie, _auth_secret(), algorithms=["HS256"],
            options={"require": ["state", "nonce", "verifier", "iat", "exp"]},
        )
        if not secrets.compare_digest(state, flow["state"]):
            raise GoogleOAuthError("OAuth state mismatch")
        link_user_id = UUID(flow["link_user_id"]) if flow.get("link_user_id") else None
        if link_user_id and link_user_id != user_id:
            raise GoogleOAuthError("Linking session changed")
    except (jwt.PyJWTError, GoogleOAuthError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Google oturum isteği geçersiz") from exc
    if error or not code:
        return _google_result_redirect("cancelled")
    try:
        token = exchange_code(settings, code=code, verifier=flow["verifier"])
        identity = verify_identity(token, client_id=settings.client_id, nonce=flow["nonce"])
        row = _google_user(
            identity["subject"], identity["email"], identity["name"],
            link_user_id=link_user_id, context=AuditContext.from_request(request),
        )
    except GoogleAccountExists:
        return _google_result_redirect("account_exists")
    except GoogleOAuthError:
        return _google_result_redirect("failed")
    response = _google_result_redirect(linked=bool(link_user_id))
    _issue_auth_response(response, row)
    return response
