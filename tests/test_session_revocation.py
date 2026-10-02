"""Çıkış jetonu gerçekten iptal eder: durumsuz JWT, `users.sessions_valid_after` ile sınırlanır."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from api.auth import routes
from api.auth.security import TokenError, create_access_token, decode_access_token_claims

pytestmark = pytest.mark.real_sessions

SECRET = "test-secret-that-is-longer-than-thirty-two-characters"
USER = uuid4()


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeUsers:
    """`users.sessions_valid_after` için asgari sahte bağlantı; sorgu sayısını da tutar."""

    def __init__(self, valid_after: datetime | None = None, *, fail: bool = False):
        self.valid_after = valid_after
        self.fail = fail
        self.reads = 0
        self.writes = 0

    @contextmanager
    def connection(self):
        if self.fail:
            raise psycopg.OperationalError("veritabanı yok")
        yield self

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("SELECT"):
            self.reads += 1
            return _Result({"sessions_valid_after": self.valid_after})
        self.writes += 1
        self.valid_after = datetime.now(timezone.utc)
        return _Result(None)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    routes._sessions_valid_after_cache.clear()
    monkeypatch.setattr(routes, "_auth_secret", lambda: SECRET)
    yield
    routes._sessions_valid_after_cache.clear()


def _use(monkeypatch, users: FakeUsers) -> None:
    monkeypatch.setattr(routes, "admin_database_connection", users.connection)


def _token(*, issued_ago: int = 0) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(USER), "iat": now - timedelta(seconds=issued_ago), "exp": now + timedelta(minutes=30)},
        SECRET,
        algorithm="HS256",
    )


def test_claims_expose_user_and_issue_time():
    token, _ = create_access_token(user_id=USER, secret=SECRET, expires_minutes=5)
    user_id, issued_at = decode_access_token_claims(token, secret=SECRET)
    assert user_id == USER and abs(issued_at - int(datetime.now(timezone.utc).timestamp())) <= 2


def test_token_without_issue_time_is_rejected():
    bare = jwt.encode({"sub": str(USER), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}, SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        decode_access_token_claims(bare, secret=SECRET)


def test_session_without_revocation_is_valid(monkeypatch):
    _use(monkeypatch, FakeUsers(None))
    assert routes.resolve_session(_token()) == USER


def test_token_issued_before_logout_is_revoked_and_a_later_one_is_not(monkeypatch):
    revoked_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    _use(monkeypatch, FakeUsers(revoked_at))
    with pytest.raises(TokenError, match="sonlandırıldı"):
        routes.resolve_session(_token(issued_ago=3600))
    routes._sessions_valid_after_cache.clear()
    assert routes.resolve_session(_token(issued_ago=5)) == USER  # çıkıştan sonra yeni giriş


def test_validity_is_cached_to_avoid_a_database_read_per_request(monkeypatch):
    users = FakeUsers(None)
    _use(monkeypatch, users)
    for _ in range(20):
        routes.resolve_session(_token())
    assert users.reads == 1


def test_revoking_clears_the_local_cache_so_logout_takes_effect_at_once(monkeypatch):
    users = FakeUsers(None)
    _use(monkeypatch, users)
    old = _token(issued_ago=120)
    assert routes.resolve_session(old) == USER  # önbelleğe "iptal yok" yazıldı
    routes.revoke_sessions(USER)
    assert users.writes == 1
    with pytest.raises(TokenError):
        routes.resolve_session(old)  # önbellek beklemeden iptal görülür


def _app(monkeypatch, users: FakeUsers) -> TestClient:
    _use(monkeypatch, users)
    monkeypatch.setattr(routes, "record_event_standalone", lambda **kwargs: None)
    monkeypatch.setattr(routes, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(
        routes, "get_settings",
        lambda: SimpleNamespace(jwt_secret=SECRET, jwt_expire_minutes=5, auth_cookie_secure=False, allow_registration=True),
    )
    app = FastAPI()
    app.include_router(routes.router)

    @app.get("/whoami")
    def whoami(user_id=routes.Depends(routes.current_user_id)):
        return {"id": str(user_id)}

    return TestClient(app)


def test_logout_makes_the_same_bearer_token_unusable(monkeypatch):
    client = _app(monkeypatch, FakeUsers(None))
    token = _token(issued_ago=60)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/whoami", headers=headers).status_code == 200
    assert client.post("/api/auth/logout", headers=headers).status_code == 204
    after = client.get("/whoami", headers=headers)
    assert after.status_code == 401


def test_unreadable_revocation_state_is_not_treated_as_logged_in(monkeypatch):
    client = _app(monkeypatch, FakeUsers(None, fail=True))
    assert client.get("/whoami", headers={"Authorization": f"Bearer {_token()}"}).status_code == 503


def test_optional_auth_falls_back_to_anonymous_when_state_is_unreadable(monkeypatch):
    _use(monkeypatch, FakeUsers(None, fail=True))
    assert routes.optional_current_user_id(SimpleNamespace(credentials=_token()), None) is None


def test_logout_still_clears_the_cookie_when_revocation_cannot_be_written(monkeypatch):
    users = FakeUsers(None)
    client = _app(monkeypatch, users)
    token = _token(issued_ago=60)
    client.get("/whoami", headers={"Authorization": f"Bearer {token}"})  # önbelleği ısıt
    users.fail = True
    response = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 204
    assert "nhr_access_token" in response.headers.get("set-cookie", "")


DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="NHR_TEST_DATABASE_URL gerekir")
def test_column_exists_and_defaults_to_null():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'sessions_valid_after'"
        ).fetchone()
    assert row == {"data_type": "timestamp with time zone", "is_nullable": "YES"}
