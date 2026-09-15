from __future__ import annotations

from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.errors import UniqueViolation

from api.auth.schemas import (
    AuthResponse,
    AuthStatusResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
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
def register(request: RegisterRequest, response: Response) -> AuthResponse:
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
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Bu e-posta zaten kayıtlı") from exc
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Kullanıcı kaydı oluşturulamadı") from exc

    return _issue_auth_response(response, row)


@router.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, response: Response) -> AuthResponse:
    _auth_secret()
    email = str(request.email).strip().lower()
    try:
        with admin_database_connection() as connection, connection.transaction():
            row = connection.execute(
                _USER_SELECT.format(field="email"), (email,)
            ).fetchone()
            valid = verify_password(request.password, row["password_hash"] if row else None)
            if not row or not valid or row["status"] != "active":
                raise HTTPException(status_code=401, detail="E-posta veya parola hatalı")
            connection.execute(
                "UPDATE users SET last_login_at = NOW() WHERE id = %s", (row["id"],)
            )
    except HTTPException:
        raise
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Oturum açılamadı") from exc

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
def logout(response: Response) -> Response:
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
