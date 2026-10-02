from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import google_oauth, routes


SECRET = "google-oauth-test-secret-longer-than-thirty-two-chars"
SETTINGS = google_oauth.GoogleOAuthSettings(
    client_id="test-client.apps.googleusercontent.com",
    client_secret="test-only-secret",
    redirect_uri="http://localhost:8766/api/auth/google/callback",
    web_callback_url="http://localhost:3000/auth/callback",
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "google_settings", lambda: SETTINGS)
    monkeypatch.setattr(
        routes, "get_settings",
        lambda: SimpleNamespace(
            jwt_secret=SECRET, jwt_expire_minutes=10, auth_cookie_secure=False,
            allow_registration=True,
        ),
    )
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_google_status_is_disabled_without_credentials(client, monkeypatch):
    monkeypatch.setattr(
        routes, "google_settings",
        lambda: google_oauth.GoogleOAuthSettings("", "", SETTINGS.redirect_uri, SETTINGS.web_callback_url),
    )
    assert client.get("/api/auth/google/status").json() == {"configured": False}
    assert client.get("/api/auth/google/start").status_code == 503


def test_google_status_requires_migration_even_with_credentials(client, monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(routes, "admin_database_connection", lambda: connection)
    connection.migration_ready = False
    assert client.get("/api/auth/google/status").json() == {"configured": False}
    connection.migration_ready = True
    assert client.get("/api/auth/google/status").json() == {"configured": True}


def test_google_start_uses_state_nonce_pkce_and_httponly_short_lived_cookie(client):
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 303
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert urlparse(response.headers["location"]).netloc == "accounts.google.com"
    assert params["scope"] == ["openid email profile"]
    assert params["redirect_uri"] == [SETTINGS.redirect_uri]
    assert params["code_challenge_method"] == ["S256"]
    cookie = response.cookies[google_oauth.FLOW_COOKIE]
    flow = jwt.decode(cookie, SECRET, algorithms=["HS256"])
    assert flow["state"] == params["state"][0]
    assert flow["nonce"] == params["nonce"][0]
    expected = base64.urlsafe_b64encode(hashlib.sha256(flow["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "max-age=600" in response.headers["set-cookie"].lower()
    assert "no-store" == response.headers["cache-control"]


def test_callback_rejects_mismatched_state_before_token_exchange(client, monkeypatch):
    started = client.get("/api/auth/google/start", follow_redirects=False)
    monkeypatch.setattr(routes, "exchange_code", lambda *_args, **_kwargs: pytest.fail("token exchange reached"))
    response = client.get("/api/auth/google/callback?state=wrong&code=fake", follow_redirects=False)
    assert started.status_code == 303
    assert response.status_code == 400
    assert routes.COOKIE_NAME not in response.cookies


def test_link_requires_existing_session_and_rejects_account_switch(client, monkeypatch):
    assert client.get("/api/auth/google/start?link=true", follow_redirects=False).status_code == 401
    first, _ = routes.create_access_token(user_id=uuid4(), secret=SECRET, expires_minutes=10)
    second, _ = routes.create_access_token(user_id=uuid4(), secret=SECRET, expires_minutes=10)
    client.cookies.set(routes.COOKIE_NAME, first)
    start = client.get("/api/auth/google/start?link=true", follow_redirects=False)
    assert start.status_code == 303
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    client.cookies.set(routes.COOKIE_NAME, second)
    monkeypatch.setattr(routes, "exchange_code", lambda *_args, **_kwargs: pytest.fail("token exchange reached"))
    callback = client.get(
        f"/api/auth/google/callback?state={state}&code=fake", follow_redirects=False
    )
    assert callback.status_code == 400


def test_callback_issues_our_session_without_exposing_google_tokens(client, monkeypatch):
    user_id = uuid4()
    row = {
        "id": user_id, "email": "new@gmail.com", "full_name": "New Lawyer",
        "status": "active", "roles": ["lawyer"],
        "created_at": datetime.now(timezone.utc), "password_hash": None,
    }
    monkeypatch.setattr(routes, "exchange_code", lambda *_args, **_kwargs: "google-sensitive-id-token")
    monkeypatch.setattr(
        routes, "verify_identity",
        lambda *_args, **_kwargs: {"subject": "google-stable-sub", "email": "new@gmail.com", "name": "New Lawyer"},
    )
    monkeypatch.setattr(routes, "_google_user", lambda *_args, **_kwargs: row)
    start = client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/api/auth/google/callback?state={state}&code=single-use-code", follow_redirects=False
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == SETTINGS.web_callback_url
    assert routes.COOKIE_NAME in callback.cookies
    assert "google-sensitive-id-token" not in str(callback.headers)
    assert routes.decode_access_token_claims(callback.cookies[routes.COOKIE_NAME], secret=SECRET)[0] == user_id


class _Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, *, existing_email=False, row_email="new@gmail.com"):
        self.existing_email = existing_email
        self.row_email = row_email
        self.statements = []
        self.user_id = uuid4()
        self.migration_ready = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, statement, params=None):
        self.statements.append((statement, params))
        if "to_regclass" in statement:
            return _Cursor({"ready": self.migration_ready})
        if "FROM auth_google_identities WHERE google_subject" in statement:
            return _Cursor(None)
        if "FROM users WHERE lower(email)" in statement:
            return _Cursor({"exists": True} if self.existing_email else None)
        if "INSERT INTO users" in statement:
            self.user_id = params[0]
            return _Cursor(None)
        if "FROM users" in statement:
            return _Cursor({
                "id": self.user_id, "email": self.row_email,
                "full_name": "New Lawyer", "status": "active", "roles": ["lawyer"],
                "created_at": datetime.now(timezone.utc), "password_hash": None,
            })
        return _Cursor(None)


def test_existing_password_account_is_not_silently_linked_by_matching_email(monkeypatch):
    connection = _Connection(existing_email=True)
    monkeypatch.setattr(routes, "admin_database_connection", lambda: connection)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(allow_registration=True))
    with pytest.raises(google_oauth.GoogleOAuthError, match="explicit linking"):
        routes._google_user(
            "stable-sub", "existing@gmail.com", "Name",
            link_user_id=None, context=SimpleNamespace(),
        )
    assert not any("INSERT INTO" in sql for sql, _ in connection.statements)


def test_new_google_account_gets_separate_subject_identity_and_lawyer_role(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(routes, "admin_database_connection", lambda: connection)
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(allow_registration=True))
    events = []
    monkeypatch.setattr(routes, "record_event", lambda _connection, **event: events.append(event))
    row = routes._google_user(
        "stable-sub", "new@gmail.com", "New Lawyer",
        link_user_id=None, context=SimpleNamespace(),
    )
    assert row["email"] == "new@gmail.com"
    assert any("INSERT INTO user_roles" in sql for sql, _ in connection.statements)
    assert any("INSERT INTO auth_google_identities" in sql for sql, _ in connection.statements)
    assert {event["action"] for event in events} == {routes.AUTH_REGISTER, routes.AUTH_LOGIN}
    assert "stable-sub" not in str(events)


def test_explicit_link_requires_same_verified_email_and_never_creates_new_user(monkeypatch):
    connection = _Connection(row_email="existing@gmail.com")
    monkeypatch.setattr(routes, "admin_database_connection", lambda: connection)
    monkeypatch.setattr(routes, "record_event", lambda *_args, **_kwargs: None)
    routes._google_user(
        "stable-sub", "existing@gmail.com", "Name",
        link_user_id=connection.user_id, context=SimpleNamespace(),
    )
    assert any("INSERT INTO auth_google_identities" in sql for sql, _ in connection.statements)
    assert not any("INSERT INTO users" in sql for sql, _ in connection.statements)
    other = _Connection(row_email="someone@example.com")
    monkeypatch.setattr(routes, "admin_database_connection", lambda: other)
    with pytest.raises(google_oauth.GoogleOAuthError):
        routes._google_user(
            "other-sub", "existing@gmail.com", "Name",
            link_user_id=other.user_id, context=SimpleNamespace(),
        )
    assert not any("INSERT INTO auth_google_identities" in sql for sql, _ in other.statements)


def test_google_id_token_requires_right_audience_nonce_and_verified_email(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        google_oauth, "_jwks",
        SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=private_key.public_key())),
    )
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "https://accounts.google.com", "sub": "123456", "aud": SETTINGS.client_id,
        "iat": now, "exp": now + timedelta(minutes=5), "nonce": "correct",
        "email": "new@gmail.com", "email_verified": True, "name": "New Lawyer",
    }
    def token(**changes):
        return jwt.encode({**claims, **changes}, private_key, algorithm="RS256")

    assert google_oauth.verify_identity(token(), client_id=SETTINGS.client_id, nonce="correct")["subject"] == "123456"
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.verify_identity(token(aud="other"), client_id=SETTINGS.client_id, nonce="correct")
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.verify_identity(token(), client_id=SETTINGS.client_id, nonce="wrong")
    with pytest.raises(google_oauth.GoogleOAuthError):
        google_oauth.verify_identity(token(email_verified=False), client_id=SETTINGS.client_id, nonce="correct")
