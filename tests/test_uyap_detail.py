"""UYAP dosya bilgileri (taraflar, safahat, dosya hesabı, tahsilat): sunucu eksiksizliği kendisi hesaplar; kullanıcı izolasyonu; evraksız dosya."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import uyap_cases, uyap_detail
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)

REQUEST = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"}, state=SimpleNamespace())
COURT = "Ankara Banka Alacakları İcra Dairesi"


def _table(rows=3, declared=None, complete=True, title="", headers=("Rol", "Adı")):
    return {"title": title, "headers": list(headers), "rows": [[f"r{i}", f"v{i}"] for i in range(rows)],
            "declared": rows if declared is None else declared, "complete": complete}


def _tabs(**overrides):
    tabs = [
        {"key": "bilgiler", "label": "Dosya Bilgileri", "pairs": [{"label": "Türü", "value": "İcra Dosyası"}], "tables": [], "complete": True},
        {"key": "hesap", "label": "Dosya Hesabı", "pairs": [{"label": "Toplam Alacak", "value": "13.783,00 TL"}], "tables": [], "complete": True},
        {"key": "taraflar", "label": "Taraf Bilgileri", "pairs": [], "tables": [_table(rows=2)], "complete": True},
        {"key": "safahat", "label": "Safahat", "pairs": [], "tables": [_table(rows=73, title="")], "complete": True},
    ]
    return [{**tab, **overrides.get(tab["key"], {})} for tab in tabs]


def _detail(**values):
    return uyap_detail.CaseDetail(**{"esas": "2025/148157", "birim": COURT, "tabs": _tabs(), "complete": True, **values})


def test_endpoints_require_a_session():
    client = TestClient(app)
    assert client.get(f"/api/office/uyap/case-detail/{uuid4()}").status_code == 401
    assert client.post("/api/office/uyap/case-detail", json={"esas": "2025/1", "birim": COURT, "tabs": _tabs()}).status_code == 401


def test_shape_has_no_row_limit_but_bounds_cells_and_columns():
    huge = uyap_detail.DetailTable(headers=["a"], rows=[["x" * 10_000] * 100 for _ in range(2000)], declared=2000, complete=True)
    assert len(huge.rows) == 2000  # satır sayısı sınırsız
    assert all(len(row) == uyap_detail.MAX_COLUMNS and len(row[0]) == uyap_detail.MAX_CELL_CHARS for row in huge.rows[:3])
    with pytest.raises(ValidationError):
        uyap_detail.CaseDetail(esas="2025/1", birim=COURT, tabs=[])
    with pytest.raises(ValidationError):
        uyap_detail.DetailTable(declared=-1)
    with pytest.raises(ValidationError):
        uyap_detail.DetailPair(label="x" * 161, value="")


def test_completeness_is_recomputed_from_the_row_counts_not_taken_from_the_client():
    tabs = uyap_detail.CaseDetail(**_detail().model_dump() | {"tabs": _tabs(safahat={"tables": [_table(rows=73, declared=75)]})}).tabs
    stored, complete, problems = uyap_detail.verified_tabs(tabs)
    safahat = next(tab for tab in stored if tab["key"] == "safahat")
    # İstemci "tamam" dese de UYAP 75 yazıp 73 satır geldiyse tamam değildir.
    assert complete is False and safahat["complete"] is False and safahat["tables"][0]["complete"] is False
    assert problems == ["Safahat: UYAP 75 kayıt yazıyor, 73 kayıt alındı."]


def test_unknown_tabs_are_never_stored_and_a_table_without_a_declared_count_is_accepted():
    tabs = uyap_detail.CaseDetail(**_detail().model_dump() | {"tabs": _tabs() + [
        {"key": "odeme", "label": "Ödeme", "pairs": [{"label": "x", "value": "y"}], "tables": [], "complete": True},
        {"key": "tahsilat", "label": "Tah./Red. Bilgileri", "pairs": [], "tables": [_table(rows=1, declared=None) | {"declared": None}], "complete": True},
    ]}).tabs
    stored, complete, problems = uyap_detail.verified_tabs(tabs)
    assert [tab["key"] for tab in stored] == ["bilgiler", "hesap", "taraflar", "safahat", "tahsilat"]  # "odeme" saklanmadı
    assert complete is True and problems == []


def test_an_unloaded_empty_pane_cannot_be_declared_complete_but_a_verified_zero_row_table_can():
    tab = uyap_detail.DetailTab(key="hesap", label="Dosya Hesabı", complete=True)
    stored, complete, problems = uyap_detail.verified_tabs([tab])
    assert complete is False and stored[0]["complete"] is False
    assert problems == ["Dosya Hesabı: içerik veya doğrulanmış boş sonuç yok."]
    tab.tables = [uyap_detail.DetailTable(headers=[], rows=[], declared=0, complete=True)]
    stored, complete, problems = uyap_detail.verified_tabs([tab])
    assert complete is True and problems == []


def test_an_empty_table_without_a_zero_count_is_not_a_verified_empty_result():
    tab = uyap_detail.DetailTab(key="safahat", label="Safahat", complete=True,
                               tables=[uyap_detail.DetailTable(rows=[], declared=None, complete=True)])
    stored, complete, problems = uyap_detail.verified_tabs([tab])
    assert complete is False and stored[0]["tables"][0]["complete"] is False
    assert problems == ["Safahat: boş tablonun sıfır kayıt olduğu doğrulanamadı."]


@pytest.mark.parametrize("key,valid", [("tahsilat", True), ("safahat", False)])
def test_static_reddiyat_evidence_is_scoped_and_persisted(key, valid):
    table = uyap_detail.DetailTable(title="Reddiyat detayı", headers=[
        "Makbuz No", "Reddiyat Tarihi", "Reddiyat Nedeni", "Ödenecek Kişi", "Reddiyat Miktar",
        "Gelir Vergisi", "Damga Vergisi", "Tahsil Harcı", "Cezaevi Harcı", "Suret Harcı",
        "Başvuru Harcı", "Ödenecek Tutar"], rows=[], declared=0, complete=True,
        empty_evidence="uyap_static_reddiyat_detail")
    stored, complete, _ = uyap_detail.verified_tabs([
        uyap_detail.DetailTab(key=key, tables=[table], complete=True)])
    assert complete is valid
    assert stored[0]["tables"][0]["empty_evidence"] == "uyap_static_reddiyat_detail"


@pytest.mark.parametrize("headers,valid", [
    # Ceza dosyalarında canlıda ölçülen 9 sütunlu düzen (2026-10-16).
    (["Makbuz No", "Durum", "Reddiyat Tarihi", "Reddiyat Nedeni", "Ödenecek Kişi", "Ödenecek Miktar",
      "Gelir Vergisi", "Damga Vergisi", "Net Ödenecek Miktar"], True),
    # Benzer görünen ama reddiyat detayı olmayan tablolar istisnadan yararlanamaz.
    (["Makbuz No", "Tahsilat Tarihi", "Yatırılan Miktar", "Ödenebilir Miktar", "A", "B", "C", "D"], False),
    (["Dosya No", "Reddiyat Tarihi", "Reddiyat Nedeni", "Ödenecek Kişi", "A", "B", "C", "Ödenecek Tutar"], False),
    (["Makbuz No", "Reddiyat Tarihi", "Reddiyat Nedeni", "Ödenecek Tutar"], False),
])
def test_static_reddiyat_schema_is_recognized_by_column_names(headers, valid):
    table = uyap_detail.DetailTable(title="Reddiyat detayı", headers=headers, rows=[], declared=0, complete=True,
                                    empty_evidence="uyap_static_reddiyat_detail")
    _, complete, _ = uyap_detail.verified_tabs([uyap_detail.DetailTab(key="tahsilat", tables=[table], complete=True)])
    assert complete is valid


def _world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(uyap_detail, "authenticated_database_connection", as_user)
    monkeypatch.setattr(uyap_detail, "record_event", lambda *a, **k: None)
    monkeypatch.setattr(uyap_cases, "record_event", lambda *a, **k: None)
    return db


def _case(world, owner, number="2025/148157", court=COURT):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, %s, %s, %s, 'x')",
        (case_id, owner, number, number, court),
    )
    return case_id


def _row(world, case_id):
    world.become(None)
    return world.connection.execute("SELECT * FROM office_uyap_case_detail WHERE case_id = %s", (case_id,)).fetchone()


@needs_db
def test_detail_is_saved_for_the_matching_case_and_replaced_not_duplicated(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    case_id = _case(world, world.alice)

    saved = uyap_detail.save_case_detail(_detail(), world.alice, REQUEST)
    assert saved["status"] == "saved" and saved["case_id"] == case_id and saved["complete"] is True and saved["case_created"] is False
    row = _row(world, case_id)
    assert row["complete"] is True and [tab["key"] for tab in row["tabs"]] == ["bilgiler", "hesap", "taraflar", "safahat"]
    assert row["tabs"][1]["pairs"] == [{"label": "Toplam Alacak", "value": "13.783,00 TL"}]  # UYAP'ın yazdığı metin aynen

    uyap_detail.save_case_detail(_detail(tabs=_tabs(safahat={"tables": [_table(rows=73, declared=80)]})), world.alice, REQUEST)
    row = _row(world, case_id)
    assert row["complete"] is False and "UYAP 80 kayıt yazıyor, 73 kayıt alındı." in row["problems"][0]
    world.become(None)
    assert world.connection.execute("SELECT count(*) AS n FROM office_uyap_case_detail WHERE case_id = %s", (case_id,)).fetchone()["n"] == 1


@needs_db
def test_a_file_without_any_evrak_still_gets_its_case_and_details(db, monkeypatch):  # noqa: F811
    """UYAP "evrak bilgisi bulunamadı" diyen eski icra dosyası: evrak yok ama dosya bilgileri kaybolmasın."""
    world = _world(db, monkeypatch)
    saved = uyap_detail.save_case_detail(_detail(esas="2010/8096", birim="(Kapatılan)Ankara 13. İcra Dairesi"), world.alice, REQUEST)

    assert saved["status"] == "saved" and saved["case_created"] is True
    world.become(None)
    case = world.connection.execute("SELECT status, owner_id, client_id, esas_no FROM office_cases WHERE id = %s", (saved["case_id"],)).fetchone()
    assert (case["status"], case["owner_id"], case["client_id"], case["esas_no"]) == ("pending", world.alice, None, "2010/8096")


@needs_db
def test_ambiguous_or_unidentifiable_files_are_not_written(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    _case(world, world.alice)
    _case(world, world.alice)  # aynı esas + aynı daire ikinci kez
    assert uyap_detail.save_case_detail(_detail(), world.alice, REQUEST) == {"status": "ambiguous"}
    assert uyap_detail.save_case_detail(_detail(esas="numarasız"), world.alice, REQUEST) == {"status": "missing_metadata"}
    with pytest.raises(HTTPException) as caught:
        uyap_detail.save_case_detail(_detail(tabs=[{"key": "yabanci", "label": "x"}]), world.alice, REQUEST)
    assert caught.value.status_code == 422  # yalnız bilinen sekmeler saklanır; saklanacak bir şey yok


@needs_db
def test_another_users_detail_is_neither_readable_nor_writable(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    mine = _case(world, world.alice)
    uyap_detail.save_case_detail(_detail(), world.alice, REQUEST)

    with pytest.raises(HTTPException) as caught:
        uyap_detail.read_case_detail(mine, world.bob)  # Bob başkasının dosya bilgisini göremez (RLS)
    assert caught.value.status_code == 404
    assert uyap_detail.read_case_detail(mine, world.alice)["complete"] is True
    # Bob aynı numarayı yollarsa kendi (yeni) davasına yazar; Alice'in kaydı değişmez.
    bob = uyap_detail.save_case_detail(_detail(tabs=_tabs(bilgiler={"pairs": [{"label": "Türü", "value": "BOB"}]})), world.bob, REQUEST)
    assert bob["case_id"] != mine and bob["case_created"] is True
    assert uyap_detail.read_case_detail(mine, world.alice)["tabs"][0]["pairs"] == [{"label": "Türü", "value": "İcra Dosyası"}]


@needs_db
def test_kvkk_export_includes_the_users_own_detail_and_sync_rows_only(db, monkeypatch):  # noqa: F811
    from api import office
    from api.account_export import build_export

    world = _world(db, monkeypatch)
    mine = _case(world, world.alice)
    uyap_detail.save_case_detail(_detail(), world.alice, REQUEST)
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_uyap_case_sync (case_id, owner_id, complete) VALUES (%s, %s, true)", (mine, world.alice)
    )
    tables = {**office.TABLES, **office.EXPORT_ONLY_TABLES}

    world.become(world.alice)
    exported = build_export(world.connection, world.alice, tables)["office"]
    assert [row["case_id"] for row in exported["uyap_case_detail"]] == [mine]
    assert [row["case_id"] for row in exported["uyap_case_sync"]] == [mine]
    world.become(world.bob)
    exported = build_export(world.connection, world.bob, tables)["office"]
    assert exported["uyap_case_detail"] == [] and exported["uyap_case_sync"] == []  # başkasının satırı sızmaz (RLS)
    assert "uyap_case_detail" not in office.TABLES  # genel CRUD ucundan yazılamaz: doğrulama sonucu uydurulamasın
