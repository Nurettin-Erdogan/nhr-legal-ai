"""Dosyalar sayfasındaki sunucu tarafı arama, kapsam ve sayfalama."""

from contextlib import contextmanager
from uuid import uuid4

from api import office


def test_document_search_is_owner_scoped_paginated_and_escapes_wildcards(monkeypatch):
    owner = uuid4()
    calls = []

    class Cursor:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

        def fetchall(self):
            return self.value

    class Connection:
        def execute(self, statement, params):
            calls.append((statement, params))
            if "count(*)" in statement:
                return Cursor({"n": 52})
            return Cursor([{"id": uuid4(), "file_name": "ek.pdf"}])

    @contextmanager
    def connection(user_id):
        assert user_id == str(owner)
        yield Connection()

    monkeypatch.setattr(office, "authenticated_database_connection", connection)
    result = office.search_case_documents(owner, q="Ek_%", offset=50, limit=50)
    assert result["total"] == 52 and len(result["rows"]) == 1
    assert len(calls) == 2
    assert all("owner_id = %s AND deleted_at IS NULL" in sql for sql, _ in calls)
    assert calls[0][1] == (owner, "%Ek\\_\\%%", "%Ek\\_\\%%", "%Ek\\_\\%%", "%Ek\\_\\%%")
    assert calls[1][1][-2:] == (50, 50)
