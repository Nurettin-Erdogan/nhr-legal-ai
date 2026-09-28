"""Büro çalışma alanı uç noktaları. Bağlantı sahtelenir; veritabanı gerekmez."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import office
from api.auth.routes import current_user_id
from api.office import router

USER_ID = uuid4()
OTHER_ID = uuid4()

CLIENT_COLUMNS = {
    "id": "uuid",
    "owner_id": "uuid",
    "full_name": "text",
    "notes": "text",
    "created_at": "timestamptz",
    "updated_at": "timestamptz",
}
DOC_COLUMNS = {"id": "uuid", "owner_id": "uuid", "title": "text", "parties": "jsonb"}


def _text(statement) -> str:
    return statement if isinstance(statement, str) else statement.as_string(None)


def _client(monkeypatch, handler=lambda sql, params: []):
    executed: list[tuple[str, object]] = []

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchall(self):
            return self.value if isinstance(self.value, list) else []

        def fetchone(self):
            return self.value if not isinstance(self.value, list) else None

    class Connection:
        def execute(self, statement, params=None):
            text = _text(statement)
            executed.append((text, params))
            return Result(handler(text, params))

    @contextmanager
    def fake_auth(user_id: str):
        assert user_id == str(USER_ID)
        yield Connection()

    monkeypatch.setattr(office, "authenticated_database_connection", fake_auth)
    monkeypatch.setitem(office._column_cache, "office_clients", CLIENT_COLUMNS)
    monkeypatch.setitem(office._column_cache, "office_legal_documents", DOC_COLUMNS)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user_id] = lambda: USER_ID
    return TestClient(app), executed


def test_requires_login():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.post("/api/office/clients", json={"op": "select"}).status_code == 401
    assert client.get("/api/office/storage/download", params={"key": "x/y"}).status_code == 401


def test_unknown_table_and_column_are_rejected(monkeypatch):
    client, executed = _client(monkeypatch)

    assert client.post("/api/office/users", json={"op": "select"}).status_code == 404
    assert client.post("/api/office/activity_logs", json={"op": "select"}).status_code == 404
    bad_column = client.post(
        "/api/office/clients",
        json={"op": "select", "filters": [{"col": "id; DROP TABLE x", "op": "eq", "val": 1}]},
    )
    assert bad_column.status_code == 400
    assert not executed


def test_bulk_update_and_delete_need_a_filter(monkeypatch):
    client, executed = _client(monkeypatch)

    update = client.post("/api/office/clients", json={"op": "update", "values": {"notes": "x"}})
    delete = client.post("/api/office/clients", json={"op": "delete"})

    assert update.status_code == 400
    assert delete.status_code == 400
    assert not executed


def test_insert_forces_owner_and_reads_back_without_returning(monkeypatch):
    def handler(text, params):
        if text.startswith("SELECT"):
            return [{"id": params[0][0], "full_name": "Ayşe", "owner_id": USER_ID}]
        return []

    client, executed = _client(monkeypatch, handler)

    response = client.post(
        "/api/office/clients",
        json={
            "op": "insert",
            "values": {"full_name": "Ayşe", "owner_id": str(OTHER_ID)},
            "single": "one",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["full_name"] == "Ayşe"
    insert_sql, insert_params = next((t, p) for t, p in executed if t.startswith("INSERT INTO"))
    assert "RETURNING" not in insert_sql
    assert USER_ID in insert_params
    assert str(OTHER_ID) not in [str(value) for value in insert_params]
    assert any(t.startswith("INSERT INTO activity_logs") or "activity_logs" in t for t, _ in executed)


def test_update_cannot_change_owner_or_id(monkeypatch):
    client, executed = _client(monkeypatch, lambda text, params: [])

    response = client.post(
        "/api/office/clients",
        json={
            "op": "update",
            "values": {"owner_id": str(OTHER_ID), "id": str(OTHER_ID), "notes": "yeni"},
            "filters": [{"col": "id", "op": "eq", "val": str(uuid4())}],
        },
    )

    assert response.status_code == 200
    update_sql = next(t for t, _ in executed if t.startswith("UPDATE"))
    assert '"notes" = %s' in update_sql
    assert '"owner_id" = %s' not in update_sql
    assert '"id" = %s,' not in update_sql


def test_user_id_alias_maps_to_owner_column(monkeypatch):
    client, executed = _client(
        monkeypatch, lambda text, params: [{"id": uuid4(), "owner_id": USER_ID, "title": "T"}]
    )

    response = client.post(
        "/api/office/legal_documents",
        json={"op": "select", "filters": [{"col": "user_id", "op": "eq", "val": str(USER_ID)}]},
    )

    assert response.status_code == 200
    select_sql = executed[0][0]
    assert '"owner_id" = %s' in select_sql
    assert "user_id" not in select_sql
    assert response.json()["data"][0]["user_id"] == str(USER_ID)


def test_call_preferences_upsert_forces_owner_without_returning(monkeypatch):
    monkeypatch.setitem(office._column_cache, "office_call_settings", {
        "id": "uuid", "owner_id": "uuid", "greeting": "text",
        "business_hours_start": "time", "business_hours_end": "time",
        "voicemail_enabled": "boolean", "ai_summary_enabled": "boolean",
    })
    saved_id = uuid4()

    def handler(statement, params):
        if statement.startswith("SELECT") and 'WHERE "owner_id" = %s' in statement:
            return {"id": saved_id}
        if statement.startswith("SELECT"):
            return [{"id": saved_id, "owner_id": USER_ID, "greeting": "Merhaba"}]
        return []

    client, executed = _client(monkeypatch, handler)
    response = client.post("/api/office/call_settings", json={
        "op": "upsert", "on_conflict": "owner_id",
        "values": {"owner_id": str(OTHER_ID), "greeting": "Merhaba",
                   "business_hours_start": "09:00", "business_hours_end": "18:00",
                   "voicemail_enabled": False, "ai_summary_enabled": False},
        "single": "one",
    })
    assert response.status_code == 200, response.text
    statement, params = next((s, p) for s, p in executed if s.startswith("INSERT INTO"))
    assert 'ON CONFLICT ("owner_id") DO UPDATE' in statement
    assert "RETURNING" not in statement
    assert USER_ID in params
    assert str(OTHER_ID) not in [str(value) for value in params]
    assert response.json()["data"]["user_id"] == str(USER_ID)


@pytest.mark.parametrize(
    "key",
    [
        f"{OTHER_ID}/dosya.pdf",  # başka kullanıcının klasörü
        f"{USER_ID}/../{OTHER_ID}/dosya.pdf",  # üst dizine çıkma
        "dosya.pdf",  # klasörsüz
        f"{USER_ID}",  # yalnız klasör
    ],
)
def test_storage_paths_are_confined_to_the_users_folder(key):
    with pytest.raises(HTTPException) as error:
        office._storage_path(USER_ID, key)

    assert error.value.status_code == 403


def test_storage_path_accepts_own_folder(monkeypatch, tmp_path):
    # A filesystem unit test must not require the developer's .env / DB secrets.
    monkeypatch.setattr(office, "get_settings", lambda: SimpleNamespace(document_storage_dir=str(tmp_path)))
    path = office._storage_path(USER_ID, f"{USER_ID}/2026/dosya.pdf")

    assert path == tmp_path / "office" / str(USER_ID) / "2026" / "dosya.pdf"
