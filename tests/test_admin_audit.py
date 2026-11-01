"""Denetim günlüğü okuma ucu: yalnız yönetici, sınırlı ve parametreli sorgu."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin_audit, admin_ingestion
from api.auth.routes import current_user_id

USER_ID = uuid4()
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


class Connection:
    def __init__(self, *, admin: bool, rows=None):
        self.admin = admin
        self.rows = rows or []
        self.queries: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        outer = self

        class Result:
            def fetchone(self):
                return {"is_admin": outer.admin}

            def fetchall(self):
                return outer.rows

        return Result()


def _client(monkeypatch, connection):
    @contextmanager
    def fake_auth(user_id: str):
        yield connection

    monkeypatch.setattr(admin_ingestion, "authenticated_database_connection", fake_auth)
    monkeypatch.setattr(admin_audit, "authenticated_database_connection", fake_auth)
    app = FastAPI()
    app.include_router(admin_audit.router)
    app.dependency_overrides[current_user_id] = lambda: USER_ID
    return TestClient(app)


def _row(**overrides):
    row = {
        "id": uuid4(), "created_at": NOW, "actor_user_id": USER_ID, "action": "auth.login",
        "entity_type": "user", "entity_id": USER_ID, "project_id": None, "request_id": uuid4(),
        "ip_address": "203.0.113.7", "user_agent": "pytest", "metadata": {},
    }
    row.update(overrides)
    return row


def test_non_admin_cannot_read_the_audit_log(monkeypatch):
    connection = Connection(admin=False, rows=[_row()])
    client = _client(monkeypatch, connection)

    response = client.get("/api/admin/audit")

    assert response.status_code == 403
    assert all("activity_logs" not in sql for sql, _ in connection.queries)


def test_admin_reads_entries_newest_first_with_bound_filters(monkeypatch):
    connection = Connection(admin=True, rows=[_row(action="project.create", metadata={"matter_type": "case"})])
    client = _client(monkeypatch, connection)
    actor = uuid4()

    response = client.get(f"/api/admin/audit?action=project.create&actor_user_id={actor}&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["action"] == "project.create" and body[0]["ip_address"] == "203.0.113.7"
    sql, params = next(q for q in connection.queries if "activity_logs" in q[0])
    assert "ORDER BY created_at DESC" in sql
    assert params["action"] == "project.create" and params["actor"] == actor and params["limit"] == 10
    assert "project.create" not in sql  # değerler SQL'e gömülmez, parametre olarak gider


def test_limit_is_bounded(monkeypatch):
    client = _client(monkeypatch, Connection(admin=True))

    assert client.get("/api/admin/audit?limit=201").status_code == 422
    assert client.get("/api/admin/audit?limit=0").status_code == 422
