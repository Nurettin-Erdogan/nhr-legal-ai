"""`/api/auth/session`: giriş yapmamış ziyaretçide 401 yerine `{"user": null}`; yetkili uçlar değişmez."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import routes


def _client(monkeypatch, row):
    @contextmanager
    def connection():
        yield SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: row))

    monkeypatch.setattr(routes, "admin_database_connection", connection)
    app = FastAPI()
    app.include_router(routes.router)
    return app, TestClient(app)


def test_anonymous_visitor_gets_null_user_not_401(monkeypatch):
    _, client = _client(monkeypatch, None)
    response = client.get("/api/auth/session")
    assert response.status_code == 200 and response.json() == {"user": None}
    assert client.get("/api/auth/me").status_code == 401  # yetki gerektiren uç değişmedi


def test_invalid_token_is_anonymous_and_a_removed_or_disabled_user_is_null(monkeypatch):
    app, client = _client(monkeypatch, None)
    assert client.get("/api/auth/session", headers={"Authorization": "Bearer bozuk"}).json() == {"user": None}
    app.dependency_overrides[routes.optional_current_user_id] = lambda: uuid4()
    assert client.get("/api/auth/session").json() == {"user": None}  # kullanıcı satırı yok
    app, client = _client(monkeypatch, {"status": "disabled"})
    app.dependency_overrides[routes.optional_current_user_id] = lambda: uuid4()
    assert client.get("/api/auth/session").json() == {"user": None}


def test_signed_in_user_is_returned(monkeypatch):
    user_id = uuid4()
    app, client = _client(monkeypatch, {"status": "active"})
    app.dependency_overrides[routes.optional_current_user_id] = lambda: user_id
    user = {"id": str(user_id), "email": "a@b.c", "full_name": "A", "status": "active", "roles": [], "created_at": "2026-10-07T00:00:00Z"}
    monkeypatch.setattr(routes, "_as_user", lambda row: user)
    body = client.get("/api/auth/session").json()["user"]
    assert (body["id"], body["email"], body["status"]) == (str(user_id), "a@b.c", "active")
