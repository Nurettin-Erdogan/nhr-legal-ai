from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin_ingestion
from api.admin_ingestion import require_admin, router
from api.auth.routes import current_user_id


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user_id] = lambda: uuid4()
    return app


def test_ingestion_status_requires_admin(monkeypatch):
    @contextmanager
    def fake_auth(_user_id: str):
        class Connection:
            def execute(self, _sql):
                class Result:
                    def fetchone(self):
                        return {"is_admin": False}

                return Result()

        yield Connection()

    monkeypatch.setattr(admin_ingestion, "authenticated_database_connection", fake_auth)
    client = TestClient(_app())
    response = client.get("/api/admin/ingestion/status")
    assert response.status_code == 403


def test_ingestion_sources_visible_to_admin(monkeypatch):
    @contextmanager
    def fake_auth(_user_id: str):
        class Connection:
            def execute(self, _sql):
                class Result:
                    def fetchone(self):
                        return {"is_admin": True}

                return Result()

        yield Connection()

    monkeypatch.setattr(admin_ingestion, "authenticated_database_connection", fake_auth)
    client = TestClient(_app())
    response = client.get("/api/admin/ingestion/sources")
    assert response.status_code == 200
    body = response.json()
    assert body["active"][0]["source"] == "yargitay"
    assert {item["source"] for item in body["active"]} == {
        "yargitay",
        "danistay",
        "mevzuat",
        "kdk",
        "aym",
    }
    assert body["verification"][0]["source"] == "resmi_gazete"
    assert body["verification"][0]["status"] == "active"
    assert {item["source"] for item in body["verification"]} == {
        "resmi_gazete",
        "mevzuat_bilgi_sistemi",
    }
    assert body["planned"] == []


def test_run_rejects_non_corpus_verification_source(monkeypatch):
    @contextmanager
    def fake_auth(_user_id: str):
        class Connection:
            def execute(self, _sql):
                class Result:
                    def fetchone(self):
                        return {"is_admin": True}

                return Result()

        yield Connection()

    monkeypatch.setattr(admin_ingestion, "authenticated_database_connection", fake_auth)
    client = TestClient(_app())
    response = client.post("/api/admin/ingestion/run/resmi_gazete")
    assert response.status_code == 400


def test_require_admin_helper_is_exported():
    assert require_admin.__name__ == "require_admin"
