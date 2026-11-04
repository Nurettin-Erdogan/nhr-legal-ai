"""Picker pagination must not download document contents or bypass owner RLS."""
import json
from contextlib import contextmanager
from uuid import uuid4

import pytest

from api import office


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return None


def install(monkeypatch, rows):
    connection = Connection(rows)
    owners = []

    @contextmanager
    def database(owner):
        owners.append(owner)
        yield connection

    monkeypatch.setattr(office, "authenticated_database_connection", database)
    return connection, owners


def call(**kwargs):
    return office.document_picker(
        user_id=kwargs.pop("user_id", uuid4()), case_id=kwargs.pop("case_id", None),
        project_id=kwargs.pop("project_id", None), q=kwargs.pop("q", ""),
        offset=kwargs.pop("offset", 0), limit=kwargs.pop("limit", 50), **kwargs,
    )


def test_picker_lookahead_and_owner_context(monkeypatch):
    owner = uuid4()
    connection, owners = install(monkeypatch, [{"id": str(uuid4())} for _ in range(51)])
    response = call(user_id=owner, offset=100)
    page = json.loads(response.body)
    assert len(page["documents"]) == 50 and page["has_more"]
    assert owners == [str(owner)]
    query, params = connection.calls[-1]
    assert params == {"offset": 100, "limit": 51}
    assert "od.deleted_at IS NULL" in query
    assert "ORDER BY od.created_at DESC, od.id DESC" in query
    assert response.headers["cache-control"] == "no-store"


def test_picker_search_is_bound_and_wildcards_are_literal(monkeypatch):
    connection, _ = install(monkeypatch, [])
    response = call(q="100%_\\'", limit=2)
    query, params = connection.calls[-1]
    assert "100%" not in query
    assert params["search"] == "%100\\%\\_\\\\'%"
    assert json.loads(response.body) == {"documents": [], "has_more": False}


def test_foreign_project_is_not_read(monkeypatch):
    connection, _ = install(monkeypatch, [])
    with pytest.raises(office.HTTPException) as error:
        call(project_id=uuid4())
    assert error.value.status_code == 404
    assert len(connection.calls) == 1
