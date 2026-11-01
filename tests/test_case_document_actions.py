"""Case document attachment boundary: no network or production DB required."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import office
from api.auth.routes import current_user_id

USER, CASE, CLIENT, DOC = uuid4(), uuid4(), uuid4(), uuid4()


def setup_client(monkeypatch, tmp_path, *, case=True, document=None, fail_insert=False, fail_commit=False):
    executed, events = [], []
    opened = []

    class Connection:
        def execute(self, statement, params=None):
            executed.append((statement, params))
            if statement.startswith("INSERT") and fail_insert:
                raise psycopg.OperationalError("unavailable")
            row = None
            if statement.startswith("SELECT id, client_id FROM office_cases"):
                row = {"id": CASE, "client_id": CLIENT} if case else None
            elif statement.startswith("SELECT id, case_id"):
                row = document
            return SimpleNamespace(fetchone=lambda: row)

    @contextmanager
    def connection(user_id):
        assert user_id == str(USER)
        opened.append(1)
        yield Connection()
        # Yükleme iki işlem açar (kısa erişim denetimi, sonra kayıt); "commit hatası" kaydı yazan ikinci işlemin sonunda olur.
        if fail_commit and len(opened) >= 2:
            raise psycopg.OperationalError("commit failed")

    monkeypatch.setattr(office, "authenticated_database_connection", connection)
    monkeypatch.setattr(office, "record_event", lambda *args, **kwargs: events.append(kwargs))
    monkeypatch.setattr(office, "get_settings", lambda: SimpleNamespace(document_storage_dir=str(tmp_path)))
    app = FastAPI()
    app.include_router(office.router)
    app.dependency_overrides[current_user_id] = lambda: USER
    return TestClient(app), executed, events


def upload(client, content=b"test", name="belge.txt"):
    return client.post(f"/api/office/cases/{CASE}/documents", files={"file": (name, content, "text/plain")})


def test_upload_and_link_require_authentication():
    app = FastAPI()
    app.include_router(office.router)
    with TestClient(app) as client:
        assert upload(client).status_code == 401
        assert client.post(f"/api/office/cases/{CASE}/documents/{DOC}/link").status_code == 401


def test_upload_saves_case_client_owner_and_bytes(monkeypatch, tmp_path):
    client, statements, events = setup_client(monkeypatch, tmp_path)
    response = upload(client, name="../../belge.txt")
    assert response.status_code == 201
    assert response.json()["file_name"] == "belge.txt"
    statement, params = next(s for s in statements if s[0].startswith("INSERT"))
    assert "RETURNING" not in statement
    assert params[1:5] == (USER, CASE, CLIENT, "belge.txt")
    assert office._storage_path(USER, params[5]).read_bytes() == b"test"
    assert events[0]["action"] == "office.case_document_upload"
    assert events[0]["metadata"] == {"case_id": str(CASE), "size": 4}


def test_inaccessible_case_never_stores_file(monkeypatch, tmp_path):
    client, statements, _ = setup_client(monkeypatch, tmp_path, case=False)
    assert upload(client).status_code == 404
    assert not any(s.startswith("INSERT") for s, _ in statements)
    assert not list(tmp_path.rglob("*"))


@pytest.mark.parametrize("content,status", [(b"", 400), (b"12345", 413)])
def test_upload_size_checked_before_write(monkeypatch, tmp_path, content, status):
    client, _, _ = setup_client(monkeypatch, tmp_path)
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "4")  # işletmecinin isteğe bağlı üst sınırı; varsayılan: sınır yok
    assert upload(client, content).status_code == status
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_db_failure_cleans_only_its_new_file(monkeypatch, tmp_path):
    client, _, _ = setup_client(monkeypatch, tmp_path, fail_insert=True)
    existing = tmp_path / "keep.txt"
    existing.write_bytes(b"keep")
    assert upload(client).status_code == 503
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == [existing]


def test_ambiguous_commit_does_not_delete_possibly_committed_document(monkeypatch, tmp_path):
    client, _, _ = setup_client(monkeypatch, tmp_path, fail_commit=True)
    assert upload(client).status_code == 503
    stored = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"test"


def document(case_id=None, client_id=None, key=None):
    return {"id": DOC, "case_id": case_id, "client_id": client_id, "storage_path": key or f"{USER}/existing.txt"}


@pytest.mark.parametrize("doc,status", [
    (None, 404), (document(case_id=uuid4()), 409),
    (document(client_id=uuid4()), 409), (document(key=f"{uuid4()}/foreign.txt"), 403),
    (document(), 404),
])
def test_link_rejects_missing_foreign_conflicting_or_absent_file(monkeypatch, tmp_path, doc, status):
    client, statements, events = setup_client(monkeypatch, tmp_path, document=doc)
    assert client.post(f"/api/office/cases/{CASE}/documents/{DOC}/link").status_code == status
    assert not any(s.startswith("UPDATE") for s, _ in statements)
    assert not events


def test_link_updates_only_relationship_and_repeated_link_is_noop(monkeypatch, tmp_path):
    client, statements, events = setup_client(monkeypatch, tmp_path, document=document())
    target = office._storage_path(USER, f"{USER}/existing.txt")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"original")
    assert client.post(f"/api/office/cases/{CASE}/documents/{DOC}/link").status_code == 200
    update, params = next(s for s in statements if s[0].startswith("UPDATE"))
    assert params == (CASE, CLIENT, DOC)
    assert "storage_path" not in update
    assert "FOR UPDATE" in statements[1][0]
    assert target.read_bytes() == b"original"
    assert events[0]["action"] == "office.case_document_link"
    client, statements, events = setup_client(monkeypatch, tmp_path, document=document(case_id=CASE))
    assert client.post(f"/api/office/cases/{CASE}/documents/{DOC}/link").status_code == 200
    assert not any(s.startswith("UPDATE") for s, _ in statements)
    assert not events
