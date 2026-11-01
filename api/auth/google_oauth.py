"""Small, server-side Google OpenID Connect authorization-code flow helpers.

No Google access/refresh token is stored. The verified Google ``sub`` is the
durable identity; email is only a contact field and never an automatic link.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from email_validator import EmailNotValidError, validate_email


AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
FLOW_COOKIE = "nhr_google_flow"
FLOW_COOKIE_PATH = "/api/auth/google/callback"

_jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)


class GoogleOAuthError(ValueError):
    pass


class GoogleAccountExists(GoogleOAuthError):
    """A password account must explicitly link its Google identity."""


@dataclass(frozen=True)
class GoogleOAuthSettings:
    client_id: str
    client_secret: str
    redirect_uri: str
    web_callback_url: str

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and _safe_url(self.redirect_uri)
            and _safe_url(self.web_callback_url)
            and urlparse(self.redirect_uri).path == FLOW_COOKIE_PATH
            and urlparse(self.web_callback_url).path == "/auth/callback"
        )


def _safe_url(value: str) -> bool:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    )


def google_settings() -> GoogleOAuthSettings:
    return GoogleOAuthSettings(
        client_id=os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        redirect_uri=os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
        web_callback_url=os.getenv("GOOGLE_WEB_CALLBACK_URL", "").strip(),
    )


def new_flow() -> tuple[str, str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)


def authorization_url(
    settings: GoogleOAuthSettings, *, state: str, nonce: str, verifier: str
) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": settings.client_id,
            "redirect_uri": settings.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )


def exchange_code(settings: GoogleOAuthSettings, *, code: str, verifier: str) -> str:
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        response.raise_for_status()
        token = response.json().get("id_token")
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise GoogleOAuthError("Google token exchange failed") from exc
    if not isinstance(token, str) or not token:
        raise GoogleOAuthError("Google ID token missing")
    return token


def verify_identity(token: str, *, client_id: str, nonce: str) -> dict[str, str]:
    try:
        key = _jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce", "email", "email_verified"]},
            leeway=30,
        )
        if not secrets.compare_digest(str(claims["nonce"]), nonce):
            raise GoogleOAuthError("Google nonce mismatch")
        if claims["email_verified"] is not True:
            raise GoogleOAuthError("Google email is not verified")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise GoogleOAuthError("Invalid Google subject")
        email = validate_email(claims["email"], check_deliverability=False).normalized.lower()
        name = claims.get("name")
        return {"subject": subject, "email": email, "name": name.strip()[:150] if isinstance(name, str) else ""}
    except (jwt.PyJWTError, jwt.PyJWKClientError, EmailNotValidError, KeyError, TypeError, ValueError) as exc:
        raise GoogleOAuthError("Google identity could not be verified") from exc
