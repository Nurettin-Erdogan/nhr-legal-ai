"""UYAP eşitleme raporu: sunucu bildirilen "eksiksiz" bilgisine körü körüne güvenmez; kullanıcı izolasyonu."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import uyap_sync
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)

REQUEST = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"}, state=SimpleNamespace())
COURT = "Ankara Banka Alacakları İcra Dairesi"


def test_endpoints_require_a_session():
    client = TestClient(app)
    assert client.get("/api/office/uyap/sync-status").status_code == 401
    assert client.post("/api/office/uyap/sync-report", json={"items": [{"esas": "2025/1", "birim": COURT}]}).status_code == 401


def test_report_shape_is_bounded():
    with pytest.raises(ValidationError):
        uyap_sync.SyncReport(items=[])
    with pytest.raises(ValidationError):
        uyap_sync.SyncReport(items=[uyap_sync.SyncItem(esas="2025/1", birim=COURT)] * (uyap_sync.MAX_ITEMS + 1))
    with pytest.raises(ValidationError):
        uyap_sync.SyncItem(esas="2025/1", birim=COURT, found=-1)
    with pytest.raises(ValidationError):
        uyap_sync.SyncItem(esas="x" * 61, birim=COURT)


def _world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(uyap_sync, "authenticated_database_connection", as_user)
    monkeypatch.setattr(uyap_sync, "record_event", lambda *a, **k: None)
    return db


def _case(world, owner, number="2025/148157", court=COURT, documents=0, *, trashed=0, manual=0):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, %s, %s, %s, 'x')",
        (case_id, owner, number, number, court),
    )
    for index in range(documents + trashed + manual):
        document_id = uuid4()
        is_manual = index >= documents + trashed
        world.connection.execute(
            "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source, uyap_file_no, uyap_birim, "
            "uyap_evrak_key, deleted_at) VALUES (%s, %s, %s, 'e.pdf', %s, %s, %s, %s, %s, %s)",
            (document_id, owner, case_id, f"{owner}/{document_id}", "manual" if is_manual else "uyap-avukat-eklentisi",
             None if is_manual else number, None if is_manual else court, None if is_manual else f"evrak-{uuid4().hex}",
             "2026-01-01" if documents <= index < documents + trashed else None),
        )
    return case_id


def _report(world, owner, **item):
    values = {"esas": "2025/148157", "birim": COURT, "found": 3, "declared": 3, "missing": 0, "complete": True, **item}
    return uyap_sync.save_sync_report(uyap_sync.SyncReport(items=[uyap_sync.SyncItem(**values)]), owner, REQUEST)


def _row(world, case_id):
    world.become(None)
    return world.connection.execute("SELECT * FROM office_uyap_case_sync WHERE case_id = %s", (case_id,)).fetchone()


@needs_db
def test_a_verified_file_is_recorded_complete_with_the_servers_own_count_and_uyap_metadata(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    case_id = _case(world, world.alice, documents=3)

    result = _report(world, world.alice, yargi_turu="İcra", dosya_turu="İlamsız Takip", durum="Açık", rol="Alacaklı Vekili", acilis="23.09.2025")

    assert result["saved"] == 1
    assert result["results"][0] | {"case_id": None} == {"esas": "2025/148157", "birim": COURT, "status": "saved", "case_id": None, "complete": True, "server_documents": 3}
    row = _row(world, case_id)
    assert (row["complete"], row["found_count"], row["server_documents"], row["missing_count"], row["problems"]) == (True, 3, 3, 0, [])
    assert (row["yargi_turu"], row["dosya_turu"], row["dosya_durumu"], row["taraf_rolu"], row["acilis"]) == ("İcra", "İlamsız Takip", "Açık", "Alacaklı Vekili", "23.09.2025")


@needs_db
def test_the_browser_cannot_declare_a_file_complete_when_the_server_holds_fewer_documents(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    # UYAP ağacında 5 evrak bulundu deniyor; sunucuda 3 UYAP evrakı var (çöpteki ve elle yüklenen sayılmaz).
    case_id = _case(world, world.alice, documents=3, trashed=1, manual=2)

    result = _report(world, world.alice, found=5, declared=5)

    assert result["results"][0]["complete"] is False and result["results"][0]["server_documents"] == 3
    row = _row(world, case_id)
    assert row["complete"] is False
    assert row["problems"][0] == "Sunucuda 3 UYAP evrakı kayıtlı, UYAP ağacında 5 evrak bulundu."


@needs_db
def test_missing_documents_or_an_incomplete_claim_are_never_stored_as_complete(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    case_id = _case(world, world.alice, documents=3)

    _report(world, world.alice, found=3, missing=1, complete=True, problems=["1 evrak JurisAI'da kayıtlı görünmüyor."])
    assert _row(world, case_id)["complete"] is False
    _report(world, world.alice, complete=False, problems=["2 klasör açılamadı.", "  ", "x" * 900])
    row = _row(world, case_id)
    assert row["complete"] is False and row["problems"][0] == "2 klasör açılamadı." and len(row["problems"][1]) == 300
    # Aktarım sırasında geçici hata bildirilse de son doğrulama tamamsa dosya eksiksizdir; kayıt güncellenir (tek satır).
    _report(world, world.alice, problems=["yükleme hatası"])
    assert _row(world, case_id)["complete"] is True
    world.become(None)
    assert world.connection.execute("SELECT count(*) AS n FROM office_uyap_case_sync WHERE case_id = %s", (case_id,)).fetchone()["n"] == 1


@needs_db
def test_the_file_is_matched_by_number_and_court_and_ambiguity_is_refused(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    _case(world, world.alice, documents=1)
    other = _case(world, world.alice, court="Ankara 7. Genel İcra Dairesi", documents=1)  # aynı esas, başka daire

    assert _report(world, world.alice, birim="ANKARA 7. GENEL İCRA DAİRESİ", esas=" 2025 / 148157 ", found=1)["results"][0]["case_id"] == other
    assert _report(world, world.alice, birim="Kahramankazan İcra Dairesi")["results"][0]["status"] == "no_case"
    assert _report(world, world.alice, esas="numarasız")["results"][0]["status"] == "missing_metadata"
    _case(world, world.alice, documents=1)  # aynı esas + aynı daire ikinci kez
    assert _report(world, world.alice)["results"][0]["status"] == "ambiguous"


@needs_db
def test_another_users_file_is_neither_written_nor_listed(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    mine = _case(world, world.alice, documents=2)
    _report(world, world.alice, found=2, declared=2)

    assert _report(world, world.bob, found=2)["results"][0]["status"] == "no_case"  # Bob'un böyle bir davası yok
    assert uyap_sync.sync_status(world.bob) == {"files": [], "summary": {"files": 0, "complete": 0, "missing": 0}}
    status = uyap_sync.sync_status(world.alice)
    assert [row["case_id"] for row in status["files"]] == [mine]
    assert status["summary"] == {"files": 1, "complete": 1, "missing": 0}
    assert (status["files"][0]["esas"], status["files"][0]["birim"]) == ("2025/148157", COURT)


@needs_db
def test_a_complete_record_is_not_trusted_after_its_documents_are_removed(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    emptied = _case(world, world.alice, documents=3)
    kept = _case(world, world.alice, number="2025/2", documents=3)
    _report(world, world.alice)
    _report(world, world.alice, esas="2025/2")
    world.become(None)
    world.connection.execute("DELETE FROM office_case_documents WHERE case_id = %s", (emptied,))

    status = uyap_sync.sync_status(world.alice)

    rows = {row["case_id"]: row for row in status["files"]}
    assert (rows[emptied]["complete"], rows[emptied]["missing_count"], rows[emptied]["server_documents"], rows[emptied]["removed_since"]) == (False, 3, 0, 3)
    assert "3 evrak silinmiş" in rows[emptied]["problems"][0]
    assert (rows[kept]["complete"], rows[kept]["missing_count"], rows[kept]["removed_since"]) == (True, 0, 0)
    assert status["summary"] == {"files": 2, "complete": 1, "missing": 3}
    assert _row(world, emptied)["complete"] is True  # saklanan kayıt değişmez; sonraki doğrulama yeniler
