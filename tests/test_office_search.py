"""Çalışma alanında genel arama: Türkçe harf eşleşmesi, joker kaçışı ve kullanıcı izolasyonu."""

from __future__ import annotations

import contextlib
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from api import office_search
from api.main import app
from tests.test_case_document_rag import _case, db, needs_db  # noqa: F401  (fixture)

# --- Veritabanı gerektirmeyenler -----------------------------------------------------------------------------------------


def test_search_requires_a_session():
    assert TestClient(app).get("/api/office/search", params={"q": "demir"}).status_code == 401


def test_turkish_letter_pairs_fold_to_one_form():
    assert office_search.fold("DEMİR") == office_search.fold("demir") == office_search.fold("Demır") == "demir"
    assert office_search.fold("IŞIK ÇAĞRI ÖZGÜR") == "işik çağri özgür"


def test_wildcards_typed_by_the_user_are_escaped():
    assert office_search.like_pattern("  %50_indirim\\  ") == "%\\%50\\_indirim\\\\%"
    assert office_search.like_pattern("Ayşe   Demir") == "%ayşe demir%"


def test_too_short_query_returns_nothing_without_touching_the_database(monkeypatch):
    def forbidden(user_id):
        raise AssertionError("kısa sorguda veritabanına gidilmemeli")

    monkeypatch.setattr(office_search, "authenticated_database_connection", forbidden)
    result = office_search.search_workspace(uuid4(), q=" a ")
    assert result == {"query": "a", "cases": [], "clients": [], "documents": [], "tasks": []}


# --- Gerçek RLS'li veritabanı --------------------------------------------------------------------------------------------


def _world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(office_search, "authenticated_database_connection", as_user)
    return db


def _client(world, owner, name, **fields):
    client_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_clients (id, owner_id, full_name, phone, national_id) VALUES (%s, %s, %s, %s, %s)",
        (client_id, owner, name, fields.get("phone"), fields.get("national_id")),
    )
    return client_id


@needs_db
def test_search_finds_cases_clients_documents_and_tasks_regardless_of_turkish_case(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    client_id = _client(world, world.alice, "Ayşe DEMİR", phone="+90 532 123 45 67", national_id="10000000146")
    case_id = _case(world, world.alice, "Demir / Kaya Tahliye Davası")
    world.connection.execute("UPDATE office_cases SET client_id = %s, esas_no = '2025/321' WHERE id = %s", (client_id, case_id))
    document_id, task_id = uuid4(), uuid4()
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source) "
        "VALUES (%s, %s, %s, 'Demir ihtarname.pdf', %s, 'manual')",
        (document_id, world.alice, case_id, f"{world.alice}/{document_id}"),
    )
    world.connection.execute(
        "INSERT INTO office_tasks (id, owner_id, case_id, title) VALUES (%s, %s, %s, 'DEMİR dosyası: cevap dilekçesi')",
        (task_id, world.alice, case_id),
    )

    result = office_search.search_workspace(world.alice, q="demir")

    assert [row["id"] for row in result["cases"]] == [case_id]
    assert result["cases"][0]["client_name"] == "Ayşe DEMİR"
    assert [row["id"] for row in result["clients"]] == [client_id]
    assert [row["id"] for row in result["documents"]] == [document_id]
    assert result["documents"][0]["case_title"] == "Demir / Kaya Tahliye Davası"
    assert [row["id"] for row in result["tasks"]] == [task_id]
    # Esas numarası ve kimlik numarasıyla da bulunur; kimlik numarası yanıta konmaz.
    assert [row["id"] for row in office_search.search_workspace(world.alice, q="2025/321")["cases"]] == [case_id]
    by_identity = office_search.search_workspace(world.alice, q="10000000146")["clients"]
    assert [row["id"] for row in by_identity] == [client_id] and "national_id" not in by_identity[0]


@needs_db
def test_search_never_returns_another_users_records_or_trashed_documents(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    _client(world, world.alice, "Ayşe Demir")
    case_id = _case(world, world.alice, "Demir Davası")
    trashed = uuid4()
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source, deleted_at) "
        "VALUES (%s, %s, %s, 'Demir eski.pdf', %s, 'manual', now())",
        (trashed, world.alice, case_id, f"{world.alice}/{trashed}"),
    )

    theirs = office_search.search_workspace(world.bob, q="demir")
    mine = office_search.search_workspace(world.alice, q="demir")

    assert theirs["cases"] == theirs["clients"] == theirs["documents"] == theirs["tasks"] == []
    assert len(mine["cases"]) == 1 and len(mine["clients"]) == 1 and mine["documents"] == []


@needs_db
def test_percent_sign_matches_only_itself(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    _case(world, world.alice, "Faiz %50 uyuşmazlığı")
    _case(world, world.alice, "Başka dava")

    assert [row["title"] for row in office_search.search_workspace(world.alice, q="%5")["cases"]] == ["Faiz %50 uyuşmazlığı"]
    assert office_search.search_workspace(world.alice, q="__")["cases"] == []
