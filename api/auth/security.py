from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
DUMMY_HASH = password_hash.hash("nhr-legal-ai-dummy-password")
ALGORITHM = "HS256"


class TokenError(RuntimeError):
    pass


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, password_digest: str | None) -> bool:
    return password_hash.verify(password, password_digest or DUMMY_HASH)


def create_access_token(
    *, user_id: UUID, secret: str, expires_minutes: int
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=expires_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": expires},
        secret,
        algorithm=ALGORITHM,
    )
    return token, expires_minutes * 60


def decode_access_token(token: str, *, secret: str) -> UUID:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        return UUID(payload["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise TokenError("Geçersiz veya süresi dolmuş oturum") from exc
