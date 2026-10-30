"""Yükleme uçlarının indekslemeyi zamanlaması ve durum/yeniden indeksleme uç noktaları."""

from __future__ import annotations

import asyncio

import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import office, office_public
from api.auth.routes import current_user_id
from api.office_public import router as public_router
from tests.test_case_document_actions import CASE, USER, setup_client, upload

TOKEN = "t" * 32


# --- Zamanlama -------------------------------------------------------------------------------------


def test_manual_case_upload_schedules_indexing_for_the_new_document(monkeypatch, tmp_path, scheduled_indexing):
    client, _, _ = setup_client(monkeypatch, tmp_path)

    response = upload(client)

    assert response.status_code == 201
    [(function, args, kwargs)] = scheduled_indexing
    assert function == "_index_and_embed"
    owner, document_id, _audit, force = args
    assert owner == USER and str(document_id) == response.json()["id"] and force is False


def test_failed_upload_is_never_scheduled(monkeypatch, tmp_path, scheduled_indexing):
    client, _, _ = setup_client(monkeypatch, tmp_path, fail_insert=True)

    assert upload(client).status_code == 503
    assert scheduled_indexing == []


def test_scheduler_failure_never_breaks_the_upload(monkeypatch, tmp_path):
    client, _, _ = setup_client(monkeypatch, tmp_path)

    def broken(*args, **kwargs):
        raise RuntimeError("kuyruk dolu")

    monkeypatch.setattr(office, "schedule_index", broken)

    assert upload(client).status_code == 201


def _public_client(monkeypatch, outcome):
    document_id = uuid4()
    monkeypatch.setattr(office_public, "_owner_for_token", lambda token: (uuid4(), USER) if token == TOKEN else None)
    monkeypatch.setattr(office_public, "_uyap_account", lambda *_: asyncio.sleep(0, result=uuid4()))  # UYAP kişisi ayrıca sınanır (test_uyap_account.py)
    monkeypatch.setattr(office_public, "_mark", lambda *_, **__: asyncio.sleep(0))
    monkeypatch.setattr(office_public, "_store", lambda owner_id, **kw: (outcome, document_id))
    app = FastAPI()
    app.include_router(public_router)
    return TestClient(app), document_id


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_extension_ingest_schedules_only_newly_inserted_documents(monkeypatch, scheduled_indexing):
    client, document_id = _public_client(monkeypatch, "inserted")

    client.post(
        "/api/public/uyap-ingest",
        json={"token": TOKEN, "files": [{"name": "karar.udf", "contentBase64": _b64(b"PK")}]},
    )

    [(function, args, _)] = scheduled_indexing
    assert function == "_index_and_embed" and args[:2] == (USER, document_id)


def test_duplicates_and_rejected_files_are_not_scheduled(monkeypatch, scheduled_indexing):
    client, _ = _public_client(monkeypatch, "duplicate")
    client.post(
        "/api/public/uyap-ingest",
        json={
            "token": TOKEN,
            "files": [
                {"name": "karar.udf", "contentBase64": _b64(b"PK")},
                {"name": "virus.exe", "contentBase64": _b64(b"MZ")},
            ],
        },
    )
    client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.pdf", b"%PDF", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert scheduled_indexing == []


def test_single_upload_schedules_a_new_document(monkeypatch, scheduled_indexing):
    client, document_id = _public_client(monkeypatch, "inserted")

    response = client.post(
        "/api/public/v1/documents/upload",
        files={"file": ("evrak.pdf", b"%PDF", "application/pdf")},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.json()["id"] == str(document_id)
    assert [item[1][:2] for item in scheduled_indexing] == [(USER, document_id)]


# --- Durum ve yeniden indeksleme -------------------------------------------------------------------


def _api(monkeypatch, *, case_exists=True, rows=None, document_exists=True):
    def fetch(statement):
        if statement.startswith("SELECT id, client_id FROM office_cases"):
            return {"id": CASE, "client_id": None} if case_exists else None
        if statement.startswith("SELECT id FROM office_case_documents"):
            return {"id": uuid4()} if document_exists else None
        return None

    class Connection:
        def execute(self, statement, params=None):
            return SimpleNamespace(fetchone=lambda: fetch(statement), fetchall=lambda: rows or [])

    @contextmanager
    def connection(user_id):
        assert user_id == str(USER)
        yield Connection()

    monkeypatch.setattr(office, "authenticated_database_connection", connection)
    app = FastAPI()
    app.include_router(office.router)
    app.dependency_overrides[current_user_id] = lambda: USER
    return TestClient(app)


def _row(name, status, *, error=None, chunks=0, embedded=0):
    return {
        "id": uuid4(),
        "file_name": name,
        "status": status,
        "processing_error": error,
        "processed_at": datetime(2026, 9, 30, tzinfo=timezone.utc) if status else None,
        "chunk_count": chunks,
        "embedded_count": embedded,
    }


def test_index_status_distinguishes_ready_failed_and_never_processed(monkeypatch):
    client = _api(
        monkeypatch,
        rows=[
            _row("karar.udf", "ready", chunks=4, embedded=4),
            _row("yarim.udf", "ready", chunks=4, embedded=1),
            _row("tarama.tif", "failed", error="OCR henüz desteklenmiyor"),
            _row("yeni.pdf", None),
        ],
    )

    body = client.get(f"/api/office/cases/{CASE}/documents/index").json()

    assert body["total"] == 4 and body["ready"] == 2
    by_name = {item["file_name"]: item for item in body["documents"]}
    assert by_name["karar.udf"]["semantic_ready"] is True
    assert by_name["yarim.udf"]["semantic_ready"] is False  # embedding tamamlanmadı; yine de aranabilir
    assert by_name["tarama.tif"]["status"] == "failed" and "OCR" in by_name["tarama.tif"]["error"]
    assert by_name["yeni.pdf"]["status"] == "pending" and by_name["yeni.pdf"]["chunk_count"] == 0


def test_index_status_and_reindex_hide_foreign_cases(monkeypatch, scheduled_indexing):
    client = _api(monkeypatch, case_exists=False)

    assert client.get(f"/api/office/cases/{CASE}/documents/index").status_code == 404
    assert client.post(f"/api/office/cases/{CASE}/documents/{uuid4()}/reindex").status_code == 404
    assert scheduled_indexing == []


def test_reindex_queues_a_forced_run_and_rejects_unknown_documents(monkeypatch, scheduled_indexing):
    document = uuid4()
    client = _api(monkeypatch)

    response = client.post(f"/api/office/cases/{CASE}/documents/{document}/reindex")

    assert response.status_code == 202 and response.json()["status"] == "queued"
    [(function, args, _)] = scheduled_indexing
    assert function == "_index_and_embed" and args[0] == USER and args[1] == document and args[3] is True

    missing = _api(monkeypatch, document_exists=False).post(
        f"/api/office/cases/{CASE}/documents/{uuid4()}/reindex"
    )
    assert missing.status_code == 404
    assert len(scheduled_indexing) == 1


def test_status_and_reindex_require_authentication():
    app = FastAPI()
    app.include_router(office.router)
    with TestClient(app) as client:
        assert client.get(f"/api/office/cases/{CASE}/documents/index").status_code == 401
        assert client.post(f"/api/office/cases/{CASE}/documents/{uuid4()}/reindex").status_code == 401


def test_status_poll_starts_indexing_of_never_processed_documents_only(monkeypatch, scheduled_indexing):
    """Genel tablo/eklenti yoluyla eklenen belge, durum sorgulanınca arka planda indekslenmeye başlar."""
    fresh = _row("yeni.pdf", None)
    client = _api(
        monkeypatch,
        rows=[_row("hazir.udf", "ready", chunks=1, embedded=1), _row("bozuk.tif", "failed", error="x"), fresh],
    )

    assert client.get(f"/api/office/cases/{CASE}/documents/index").status_code == 200

    [(function, args, _)] = scheduled_indexing  # hazır ve başarısız olanlar yeniden denenmez
    assert function == "_index_and_embed" and args[0] == USER and args[1] == fresh["id"] and args[3] is False


def test_linking_a_document_to_a_case_schedules_its_indexing(monkeypatch, tmp_path, scheduled_indexing):
    from tests.test_case_document_actions import DOC, document

    client, _, _ = setup_client(monkeypatch, tmp_path, document=document())
    target = office._storage_path(USER, f"{USER}/existing.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")

    assert client.post(f"/api/office/cases/{CASE}/documents/{DOC}/link").status_code == 200

    [(function, args, _)] = scheduled_indexing
    assert function == "_index_and_embed" and args[0] == USER and args[1] == DOC
