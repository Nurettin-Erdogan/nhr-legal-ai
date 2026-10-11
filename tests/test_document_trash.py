"""Belge çöp kutusu: gerçek RLS'li test veritabanında, işlem sonunda geri alınır."""

from __future__ import annotations

import contextlib
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from api import document_indexing as indexing
from api import document_trash as trash
from api import office, office_public, office_trash
from api.ai import retrieval
from api.auth.routes import current_user_id
from tests.test_document_indexing import _chunks, _derived, _office_doc, world  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

TEXT = "Davacı işçi 8 yıl çalışmıştır. Bilirkişi kıdem tazminatını 340.000 TL hesaplamıştır.".encode()


@pytest.fixture
def lab(world, monkeypatch):  # noqa: F811
    connection, alice, bob, files, _ = world
    as_user = indexing.authenticated_database_connection  # `world` fixture'ının RLS'li bağlantısı
    monkeypatch.setattr(trash, "authenticated_database_connection", as_user)
    monkeypatch.setattr(office, "authenticated_database_connection", as_user)
    monkeypatch.setattr(trash, "_remove_file", lambda owner, path: removed.append(path))
    removed: list[str] = []

    @contextlib.contextmanager
    def as_admin():
        connection.execute("RESET ROLE")
        yield connection

    monkeypatch.setattr(trash, "admin_database_connection", as_admin)
    yield connection, alice, bob, files, removed


def _case(connection, owner):
    connection.execute("RESET ROLE")
    case_id = uuid4()
    connection.execute("INSERT INTO office_cases (id, owner_id, title) VALUES (%s, %s, 'Dava')", (case_id, owner))
    return case_id


def _indexed(connection, owner, files, case_id=None, name="rapor.txt"):
    office_id = _office_doc(connection, owner, files, name=name, data=TEXT, case_id=case_id)
    assert indexing.index_office_document(owner, office_id).status == "ready"
    return office_id


def _cite(connection, owner, office_id, *, answer="Bilirkişi 340.000 TL hesaplamıştır. [K1]"):
    """Belgeden alıntılı bir cevap ve ona bağlı atıf kaydı oluşturur."""
    connection.execute("RESET ROLE")
    chunk = connection.execute(
        "SELECT c.id FROM document_chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.office_case_document_id = %s ORDER BY c.chunk_index LIMIT 1",
        (office_id,),
    ).fetchone()["id"]
    conversation, message = uuid4(), uuid4()
    connection.execute(
        "INSERT INTO conversations (id, created_by, title) VALUES (%s, %s, 'Sohbet')", (conversation, owner)
    )
    connection.execute(
        "INSERT INTO messages (id, conversation_id, role, content, metadata) VALUES (%s, %s, 'assistant', %s, %s)",
        (message, conversation, answer, Jsonb({"grounded": True})),
    )
    connection.execute(
        "INSERT INTO citations (message_id, document_chunk_id, citation_order, marker, source_title, "
        "source_locator, snippet, relevance_score) VALUES (%s, %s, 1, 'K1', 'rapor.txt', %s, %s, 0.9)",
        (message, chunk, Jsonb({}), "340.000 TL hesaplamıştır"),
    )
    return message


def _count(connection, sql, *params):
    connection.execute("RESET ROLE")
    return connection.execute(sql, params).fetchone()["n"]


# --- çöpe taşı / geri al -----------------------------------------------------------------------


def test_trashed_document_disappears_everywhere_and_comes_back_on_restore(lab):
    connection, alice, _, files, _ = lab
    case_id = _case(connection, alice)
    office_id = _indexed(connection, alice, files, case_id)
    assert indexing.case_document_coverage(alice, case_id)["ready"] == 1

    assert trash.trash_document(alice, office_id) is True

    assert indexing.case_document_coverage(alice, case_id) == {
        "case_id": str(case_id), "total": 0, "ready": 0, "failed": [], "pending": 0, "ocr": 0,
    }
    scope = f"SELECT count(*) AS n FROM documents AS document WHERE {retrieval._DOCUMENT_SCOPE_CASE}"
    assert _count(connection, scope.replace("%(case_id)s", "%s"), case_id) == 0  # arama kapsamı dışı
    assert indexing.sweep_unindexed(alice, case_id=case_id) == 0
    assert indexing.index_office_document(alice, office_id).status == "missing"  # yeniden indekslenmez

    assert trash.restore_document(alice, office_id) is True
    assert indexing.case_document_coverage(alice, case_id)["ready"] == 1
    assert _count(connection, scope.replace("%(case_id)s", "%s"), case_id) == 1
    assert _derived(connection, office_id)["status"] == "ready"  # yeniden indeksleme gerekmedi


def test_trash_and_restore_are_idempotent_and_owner_scoped(lab):
    connection, alice, bob, files, _ = lab
    office_id = _indexed(connection, alice, files)

    assert trash.trash_document(bob, office_id) is False  # başkasının belgesi ayırt edilmez
    assert trash.restore_document(bob, office_id) is False
    assert trash.trash_document(alice, office_id) is True
    assert trash.trash_document(alice, office_id) is False  # zaten çöpte
    assert trash.restore_document(alice, office_id) is True
    assert trash.restore_document(alice, office_id) is False  # zaten çöpte değil


def test_batch_trash_is_owner_scoped_and_deduplicates_requested_ids(lab):
    connection, alice, bob, files, _ = lab
    first = _indexed(connection, alice, files, name="birinci.txt")
    second = _indexed(connection, alice, files, name="ikinci.txt")
    other = _indexed(connection, bob, files, name="baska-kullanici.txt")

    moved = trash.trash_documents(alice, [first, second, first, other])

    assert set(moved) == {first, second}
    assert _count(
        connection,
        "SELECT count(*) AS n FROM office_case_documents WHERE id = ANY(%s) AND deleted_at IS NOT NULL",
        [first, second],
    ) == 2
    assert _count(
        connection,
        "SELECT count(*) AS n FROM office_case_documents WHERE id = %s AND deleted_at IS NULL",
        other,
    ) == 1


def test_listing_shows_only_the_owners_trash_with_days_left_and_cited_answers(lab):
    connection, alice, bob, files, _ = lab
    case_id = _case(connection, alice)
    cited = _indexed(connection, alice, files, case_id, name="atifli.txt")
    plain = _indexed(connection, alice, files, case_id, name="atifsiz.txt")
    live = _indexed(connection, alice, files, case_id, name="canli.txt")
    other = _indexed(connection, bob, files, None, name="bob.txt")
    _cite(connection, alice, cited)
    for document in (cited, plain):
        trash.trash_document(alice, document)
    trash.trash_document(bob, other)

    items = {item["file_name"]: item for item in trash.list_trash(alice)}

    assert set(items) == {"atifli.txt", "atifsiz.txt"}  # canlı ve başkasının belgesi yok
    assert items["atifli.txt"]["cited_answers"] == 1 and items["atifsiz.txt"]["cited_answers"] == 0
    assert items["atifli.txt"]["days_left"] == trash.RETENTION_DAYS
    assert {item["file_name"] for item in trash.list_trash(alice, case_id)} == {"atifli.txt", "atifsiz.txt"}
    assert trash.list_trash(alice, uuid4()) == []
    assert live  # canlı belge çöpe girmedi


def test_duplicate_check_ignores_trashed_documents(lab):
    connection, alice, _, files, _ = lab
    office_id = _office_doc(connection, alice, files, name="ayni.txt", data=TEXT)
    connection.execute("UPDATE office_case_documents SET uyap_file_no = '2025/1' WHERE id = %s", (office_id,))
    args = dict(file_name="ayni.txt", size_bytes=len(TEXT), uyap_file_no="2025/1", source=None)
    connection.execute("RESET ROLE")
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(alice),))
    assert office_public.find_duplicate(connection, **args) == office_id

    trash.trash_document(alice, office_id)
    connection.execute("RESET ROLE")
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(alice),))
    assert office_public.find_duplicate(connection, **args) is None  # tekrar yüklenebilir


# --- kalıcı silme -----------------------------------------------------------------------------


def test_permanent_delete_needs_the_trash_first(lab):
    connection, alice, bob, files, removed = lab
    office_id = _indexed(connection, alice, files)

    assert trash.delete_forever(alice, office_id).status == "not_trashed"
    assert trash.delete_forever(bob, office_id).status == "not_found"
    assert trash.delete_forever(alice, uuid4()).status == "not_found"
    assert _derived(connection, office_id) is not None and removed == []


def test_permanent_delete_removes_text_chunks_file_and_redacts_cited_answers(lab):
    connection, alice, bob, files, removed = lab
    office_id = _indexed(connection, alice, files)
    other_id = _indexed(connection, bob, files, name="bob.txt")
    message = _cite(connection, alice, office_id)
    bob_message = _cite(connection, bob, other_id, answer="Bob'un cevabı. [K1]")
    trash.trash_document(alice, office_id)

    outcome = trash.delete_forever(alice, office_id)

    assert (outcome.status, outcome.redacted_answers) == ("deleted", 1)
    connection.execute("RESET ROLE")
    assert _derived(connection, office_id) is None  # türetilmiş belge gitti
    assert _count(connection, "SELECT count(*) AS n FROM office_case_documents WHERE id = %s", office_id) == 0
    assert _count(connection, "SELECT count(*) AS n FROM citations WHERE message_id = %s", message) == 0
    row = connection.execute("SELECT content, metadata, role FROM messages WHERE id = %s", (message,)).fetchone()
    assert row["content"] == trash.REDACTED_ANSWER and "340.000" not in row["content"]
    assert row["metadata"]["redacted"] == "source_deleted" and row["role"] == "assistant"
    assert len(removed) == 1  # diskteki dosya kaldırıldı
    # Başka kullanıcının belgesi, cevabı ve atfı etkilenmedi.
    assert _derived(connection, other_id)["status"] == "ready"
    assert _count(connection, "SELECT count(*) AS n FROM citations WHERE message_id = %s", bob_message) == 1
    assert (
        connection.execute("SELECT content FROM messages WHERE id = %s", (bob_message,)).fetchone()["content"]
        == "Bob'un cevabı. [K1]"
    )


def test_deleting_an_uncited_document_redacts_nothing(lab):
    connection, alice, _, files, _ = lab
    office_id = _indexed(connection, alice, files)
    trash.trash_document(alice, office_id)

    outcome = trash.delete_forever(alice, office_id)

    assert (outcome.status, outcome.redacted_answers) == ("deleted", 0)


def test_expired_trash_is_purged_but_recent_trash_is_kept(lab):
    connection, alice, _, files, removed = lab
    old = _indexed(connection, alice, files, name="eski.txt")
    recent = _indexed(connection, alice, files, name="yeni.txt")
    live = _indexed(connection, alice, files, name="canli.txt")
    _cite(connection, alice, old)
    connection.execute("RESET ROLE")
    connection.execute(
        "UPDATE office_case_documents SET deleted_at = now() - make_interval(days => %s) WHERE id = %s",
        (trash.RETENTION_DAYS + 1, old),
    )
    connection.execute(
        "UPDATE office_case_documents SET deleted_at = now() - make_interval(days => 1) WHERE id = %s", (recent,)
    )

    assert trash.purge_expired() == 1

    remaining = {
        row["id"]
        for row in connection.execute(
            "SELECT id FROM office_case_documents WHERE id = ANY(%s)", ([old, recent, live],)
        ).fetchall()
    }
    assert remaining == {recent, live}
    assert trash.delete_forever(alice, recent, only_expired=True).status == "not_trashed"  # henüz dolmadı


# --- genel tablo ucu bu kuralları atlayamaz ---------------------------------------------------


def _query(op, **kwargs):
    return office.OfficeQuery(op=op, **kwargs)


def _generic(connection, alice, query):
    request = type("R", (), {"client": None, "headers": {}})()
    return office._run(query, "case_documents", alice, request)


def test_generic_route_hides_trashed_rows_and_refuses_to_delete(lab):
    connection, alice, _, files, _ = lab
    live = _indexed(connection, alice, files, name="canli.txt")
    gone = _indexed(connection, alice, files, name="cop.txt")
    trash.trash_document(alice, gone)

    rows = _generic(connection, alice, _query("select", columns="id,file_name")).data
    assert {row["file_name"] for row in rows} == {"canli.txt"}
    assert _generic(connection, alice, _query("select", count=True)).count == 1

    with pytest.raises(HTTPException) as error:
        _generic(connection, alice, _query("delete", filters=[office.Filter(col="id", op="eq", val=str(live))]))
    assert error.value.status_code == 409  # kalıcı silme atlanamaz
    assert _count(connection, "SELECT count(*) AS n FROM office_case_documents WHERE id = %s", live) == 1


def test_generic_route_cannot_trash_restore_or_edit_trashed_documents(lab):
    connection, alice, _, files, _ = lab
    live = _indexed(connection, alice, files, name="canli.txt")
    gone = _indexed(connection, alice, files, name="cop.txt")
    trash.trash_document(alice, gone)

    # `deleted_at` istemciden yazılamaz: belge çöpe taşınmaz.
    with pytest.raises(HTTPException) as error:
        _generic(
            connection, alice,
            _query("update", values={"deleted_at": "2020-01-01T00:00:00Z"},
                   filters=[office.Filter(col="id", op="eq", val=str(live))]),
        )
    assert error.value.status_code == 400
    assert _count(connection, "SELECT count(*) AS n FROM office_case_documents WHERE id = %s AND deleted_at IS NULL", live) == 1

    # Çöpteki belge genel uçtan geri alınamaz ya da değiştirilemez.
    result = _generic(
        connection, alice,
        _query("update", values={"deleted_at": None, "notes": "geri aldim"},
               filters=[office.Filter(col="id", op="eq", val=str(gone))]),
    )
    assert result.count == 0
    assert _count(connection, "SELECT count(*) AS n FROM office_case_documents WHERE id = %s AND deleted_at IS NOT NULL", gone) == 1


def test_generic_insert_cannot_create_an_already_trashed_document(lab):
    connection, alice, _, _, _ = lab
    path = f"{alice}/{uuid4()}"
    result = _generic(
        connection, alice,
        _query("insert", values={"file_name": "x.txt", "storage_path": path, "deleted_at": "2020-01-01T00:00:00Z"}),
    )
    assert result.data[0]["deleted_at"] is None


# --- HTTP uçları ------------------------------------------------------------------------------


@pytest.fixture
def client(lab):
    from fastapi import FastAPI

    connection, alice, bob, files, _ = lab
    app = FastAPI()
    app.include_router(office_trash.router)
    current = {"user": alice}
    app.dependency_overrides[current_user_id] = lambda: current["user"]
    return TestClient(app), current, lab


def test_http_flow_trash_list_restore_and_two_step_permanent_delete(client):
    http, current, (connection, alice, bob, files, removed) = client
    office_id = _indexed(connection, alice, files)
    _cite(connection, alice, office_id)

    assert http.delete(f"/api/office/documents/{office_id}").status_code == 409  # önce çöpe taşınmalı
    assert http.post(f"/api/office/documents/{office_id}/trash").json()["trashed"] is True
    assert http.post(f"/api/office/documents/{office_id}/trash").status_code == 404  # zaten çöpte

    listing = http.get("/api/office/documents/trash").json()
    assert listing["retention_days"] == trash.RETENTION_DAYS
    assert [(d["file_name"], d["cited_answers"]) for d in listing["documents"]] == [("rapor.txt", 1)]

    assert http.post(f"/api/office/documents/{office_id}/restore").json()["trashed"] is False
    assert http.get("/api/office/documents/trash").json()["documents"] == []

    http.post(f"/api/office/documents/{office_id}/trash")
    deleted = http.delete(f"/api/office/documents/{office_id}")
    assert deleted.status_code == 200 and deleted.json() == {
        "id": str(office_id), "deleted": True, "redacted_answers": 1,
    }
    assert http.delete(f"/api/office/documents/{office_id}").status_code == 404  # artık yok


def test_http_batch_trash_is_reversible_and_does_not_expose_other_users(client):
    http, current, (connection, alice, bob, files, _) = client
    first = _indexed(connection, alice, files, name="birinci.txt")
    second = _indexed(connection, alice, files, name="ikinci.txt")
    other = _indexed(connection, bob, files, name="baska.txt")

    response = http.post(
        "/api/office/documents/trash/batch",
        json={"document_ids": [str(first), str(second), str(first), str(other)]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "requested": 3,
        "trashed": 2,
        "not_found": 1,
        "retention_days": trash.RETENTION_DAYS,
    }
    assert {row["file_name"] for row in trash.list_trash(alice)} == {"birinci.txt", "ikinci.txt"}
    assert _count(
        connection,
        "SELECT count(*) AS n FROM office_case_documents WHERE id = %s AND deleted_at IS NULL",
        other,
    ) == 1


def test_http_other_users_documents_look_like_they_do_not_exist(client):
    http, current, (connection, alice, bob, files, _) = client
    office_id = _indexed(connection, alice, files)
    current["user"] = bob

    assert http.post(f"/api/office/documents/{office_id}/trash").status_code == 404
    assert http.post(f"/api/office/documents/{office_id}/restore").status_code == 404
    assert http.delete(f"/api/office/documents/{office_id}").status_code == 404
    assert http.get("/api/office/documents/trash").json()["documents"] == []
