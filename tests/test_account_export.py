"""KVKK veri dışa aktarma: yalnız kendi verisi, gizli alanlar yok, sınır açıkça söylenir."""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from api import account_export, office
from tests.test_case_document_rag import _case, db, needs_db  # noqa: F401  (fixture)


@pytest.fixture
def api(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(office, "authenticated_database_connection", as_user)
    return db


TOKEN = "jsai_GIZLIANAHTAR" + "x" * 30  # tetikleyici düz değeri siler, özet ve ön ek saklar


def _seed(api):
    api.become(None)
    for owner, name in ((api.alice, "Alice Müvekkil"), (api.bob, "Bob Müvekkil")):
        api.connection.execute("INSERT INTO office_clients (id, owner_id, full_name) VALUES (%s, %s, %s)", (uuid4(), owner, name))
    case = _case(api, api.alice, "Alice Davası")
    document = uuid4()
    api.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, size_bytes) VALUES (%s, %s, %s, 'dilekce.udf', %s, 5)",
        (document, api.alice, case, f"{api.alice}/gizli/yol"),
    )
    api.connection.execute("INSERT INTO office_uyap_ingest_tokens (id, owner_id, token) VALUES (%s, %s, %s)", (uuid4(), api.alice, TOKEN))
    conversation = uuid4()
    api.connection.execute("INSERT INTO conversations (id, created_by, title) VALUES (%s, %s, 'Kıdem sorusu')", (conversation, api.alice))
    api.connection.execute("INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'user', 'Kıdem tazminatı nedir?')", (uuid4(), conversation))
    api.connection.execute("INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, 'assistant', 'Cevap metni')", (uuid4(), conversation))


def _export(api, user):
    response = office.export_account_data(user_id=user, request=SimpleNamespace(client=None, headers={}))
    return response, json.loads(response.body)


@needs_db
def test_the_export_contains_only_the_callers_own_data(api):
    _seed(api)
    response, data = _export(api, api.alice)
    names = [row["full_name"] for row in data["office"]["clients"]]
    assert names == ["Alice Müvekkil"] and "Bob" not in json.dumps(data, ensure_ascii=False)
    assert data["user"]["id"] == str(api.alice) and data["office"]["cases"][0]["title"] == "Alice Davası"
    [conversation] = data["conversations"]
    assert conversation["title"] == "Kıdem sorusu" and [m["role"] for m in conversation["messages"]] == ["user", "assistant"]
    assert response.headers["content-disposition"].startswith("attachment") and response.headers["cache-control"] == "no-store"


@needs_db
def test_secrets_and_internal_paths_never_leave_the_server(api):
    _seed(api)
    _, data = _export(api, api.alice)
    text = json.dumps(data, ensure_ascii=False)
    api.become(None)
    stored = api.connection.execute("SELECT token_hash, token_prefix FROM office_uyap_ingest_tokens WHERE owner_id = %s", (api.alice,)).fetchone()
    assert stored["token_hash"]  # özet gerçekten var; dışarı çıkmamalı
    for secret in ("GIZLIANAHTAR", stored["token_hash"], stored["token_prefix"], "gizli/yol", "password_hash", "storage_path"):
        assert secret not in text
    assert "uyap_ingest_tokens" not in data["office"]
    assert data["office"]["case_documents"][0]["file_name"] == "dilekce.udf"  # üst veri gelir, iç yol gelmez


@needs_db
def test_a_user_with_no_data_gets_an_empty_but_valid_export(api):
    _, data = _export(api, api.bob)
    assert data["user"]["id"] == str(api.bob) and data["conversations"] == [] and data["office"]["clients"] == []
    assert data["truncated_tables"] == [] and data["notes"]


@needs_db
def test_the_row_cap_is_reported_not_hidden(api, monkeypatch):
    _seed(api)
    api.become(None)
    for index in range(3):
        api.connection.execute("INSERT INTO office_clients (id, owner_id, full_name) VALUES (%s, %s, %s)", (uuid4(), api.alice, f"Ek {index}"))
    monkeypatch.setattr(account_export, "MAX_ROWS", 2)
    _, data = _export(api, api.alice)
    assert "clients" in data["truncated_tables"] and len(data["office"]["clients"]) == 2


@needs_db
def test_the_export_is_audited_without_content(api):
    _seed(api)
    _export(api, api.alice)
    api.become(None)
    [event] = api.connection.execute("SELECT metadata FROM activity_logs WHERE action = 'account.export' AND actor_user_id = %s", (api.alice,)).fetchall()
    assert "Alice" not in json.dumps(event["metadata"]) and "tables" in event["metadata"]
