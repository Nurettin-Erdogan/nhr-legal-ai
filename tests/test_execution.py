"""İcra dosyaları: birim/evrak türü tanıma, makbuzdan tutar okuma ve kullanıcı izolasyonu."""

from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api import execution
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)

# --- Veritabanı gerektirmeyenler -----------------------------------------------------------------------------------------


def test_requires_a_session():
    assert TestClient(app).get("/api/office/execution/files").status_code == 401


@pytest.mark.parametrize(
    "court, expected",
    [
        ("Ankara Banka Alacakları İcra Dairesi", "takip"),
        ("(Kapatılan)Ankara 2. İcra Dairesi", "takip"),
        ("ANKARA 7. GENEL İCRA DAİRESİ", "takip"),
        ("Kahramankazan İcra Müdürlüğü", "takip"),
        ("Ankara 13. İcra Hukuk Mahkemesi", "mahkeme"),
        ("İstanbul 3. İcra Ceza Mahkemesi", "mahkeme"),
        ("Ankara 5. Sulh Hukuk Mahkemesi", None),
        ("Ankara Bölge Adliye Mahkemesi 18. Hukuk Dairesi", None),
        ("", None),
        (None, None),
    ],
)
def test_only_execution_offices_and_courts_are_recognised(court, expected):
    assert execution.execution_kind(court) == expected


@pytest.mark.parametrize(
    "doc_type, expected",
    [
        ("Tahsilat makbuzu", "tahsilat"),
        ("Tahsilat Makbuzu", "tahsilat"),
        ("Haricen Tahsil Bildirimi Talebi", "tahsilat"),
        ("Tahsil Harcı Makbuzu(Sayman Mutemet Alındısı)", "harc"),  # "tahsilat" sanılmamalı
        ("Vekalet Pulu Makbuzu", "harc"),
        ("Reddiyat makbuzu", "reddiyat"),
        ("Reddiyat Makbuzu", "reddiyat"),
        ("Reddiyat Banka Ödeme Dekontu", "reddiyat_diger"),
        ("Reddiyat Beyanı", "reddiyat_diger"),
        ("Masraf Makbuzu", "masraf"),
        ("89/1 Haciz İhbarnamesi Cevabı", "haciz"),
        ("Avukat Portal Haciz Talebi", "haciz"),
        ("İcra Daireleri Haciz Tebliğ Yazısı", "haciz"),
        ("Kapalı E-Tebliğ Mazbatası", "teblig"),
        ("Kapalı Tebligat", "teblig"),
        ("Takip Talebi", "takip_talebi"),
        ("Ödeme İcra Emri", "odeme_emri"),
        ("Borca İtiraz Talebi", "itiraz"),
        ("Dosya Hesabı Raporu", "hesap"),
        ("Takibin Dayanagi Belge", "dayanak"),
        ("Ek", "diger"),
        ("Vekaletname", "diger"),
        (None, "diger"),
    ],
)
def test_document_types_are_classified_by_their_uyap_type(doc_type, expected):
    assert execution.classify_document(doc_type) == expected


def test_a_receipt_amount_is_read_only_when_it_is_unambiguous():
    same = "Borç 1.234,50 TL\n........\n1.234,50 TL Tutarı\n(*) 1.234,50 TL\n"
    assert execution.receipt_amount(same, "tahsilat") == Decimal("1234.50")
    assert execution.receipt_amount("Tutar: 99,90TL", "masraf") == Decimal("99.90")
    # Farklı tutarlar (harç/faiz kırılımı): hangisinin makbuz tutarı olduğu bilinemez.
    assert execution.receipt_amount("Harç 12,00 TL\nAsıl 1.000,00 TL\n", "tahsilat") is None
    assert execution.receipt_amount("tutar yok", "tahsilat") is None
    assert execution.receipt_amount("", "tahsilat") is None
    # Binlik ayracı olmayan sayı ve tarih parçaları tutar sayılmaz.
    assert execution.receipt_amount("Tarih 10.04.2025 No 2025/148157", "tahsilat") is None
    assert execution.receipt_amount("1234,50 TL", "tahsilat") == Decimal("1234.50")


def _row(case_id, doc_type, doc_date=None, *, court="Ankara Banka Alacakları İcra Dairesi", no="2025/1"):
    return {
        "case_id": case_id, "case_no": no, "esas_no": no, "court": court, "status": "pending", "title": no,
        "document_id": uuid4(), "doc_type": doc_type, "doc_date": doc_date,
    }


def test_files_are_grouped_with_counts_dates_and_only_readable_receipts_are_summed():
    first, second = uuid4(), uuid4()
    rows = [
        _row(first, "Takip Talebi", date(2025, 9, 23)),
        _row(first, "Tahsilat makbuzu", date(2026, 1, 5)),
        _row(first, "Tahsilat makbuzu", date(2026, 2, 5)),
        _row(first, "Tahsilat makbuzu", date(2026, 3, 5)),
        _row(first, "Reddiyat makbuzu", date(2026, 3, 6)),
        _row(first, "Kapalı Tebligat", None),
        _row(second, "Masraf Makbuzu", date(2024, 1, 2), court="Ankara 13. İcra Hukuk Mahkemesi", no="2019/1157"),
    ]
    texts = {
        rows[1]["document_id"]: "100,00 TL Tutarı\n(*) 100,00 TL",
        rows[2]["document_id"]: "250,50 TL Tutarı",
        rows[3]["document_id"]: "Harç 12,00 TL Asıl 900,00 TL",  # belirsiz: toplama girmez
        rows[4]["document_id"]: "500,00 TL",                       # reddiyat: okunsa da toplanmaz
        rows[6]["document_id"]: "Toplam 30,00 TL",
    }

    files = execution.build_files(rows, texts)
    by_id = {item["case_id"]: item for item in files}
    one, two = by_id[first], by_id[second]

    assert files[0]["case_id"] == first  # son evrak tarihi daha yeni olan önce gelir
    assert (one["documents"], one["first_date"], one["last_date"], one["kind"]) == (6, date(2025, 9, 23), date(2026, 3, 6), "takip")
    assert one["counts"] == {"tahsilat": 3, "reddiyat": 1, "teblig": 1, "takip_talebi": 1}
    assert one["receipts"]["tahsilat"] == {"count": 3, "read": 2, "total": "350.50"}
    assert "reddiyat" not in one["receipts"]
    assert (two["kind"], two["receipts"]["masraf"]) == ("mahkeme", {"count": 1, "read": 1, "total": "30.00"})

    summary = execution.summarize(files)
    assert summary["files"] == 2 and summary["documents"] == 7
    assert (summary["verified_complete"], summary["never_verified"]) == (0, 2) and one["uyap"] is None
    assert summary["tahsilat"] == {"count": 3, "read": 2, "total": "350.50"}
    assert summary["masraf"] == {"count": 1, "read": 1, "total": "30.00"}


def test_uyap_status_and_last_verification_are_passed_through_uninterpreted():
    from datetime import datetime, timezone

    checked = datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc)
    verified, unverified = uuid4(), uuid4()
    rows = [
        {**_row(verified, "Takip Talebi", date(2025, 9, 23)), "dosya_durumu": "Kapalı ( 27.06.2025 )", "dosya_turu": "İcra Dosyası",
         "taraf_rolu": "Alacaklı", "acilis": "23.09.2025 09:00:00", "sync_complete": True, "sync_missing": 0, "sync_checked_at": checked},
        {**_row(unverified, "Takip Talebi", date(2024, 1, 1), no="2024/9"), "dosya_durumu": "Açık", "sync_complete": False, "sync_missing": 3,
         "sync_checked_at": checked},
    ]
    files = {item["case_id"]: item for item in execution.build_files(rows, {})}
    assert files[verified]["uyap"] == {"durum": "Kapalı ( 27.06.2025 )", "tur": "İcra Dosyası", "rol": "Alacaklı", "acilis": "23.09.2025 09:00:00",
                                       "complete": True, "missing": 0, "checked_at": checked}
    assert files[unverified]["uyap"]["complete"] is False and files[unverified]["uyap"]["missing"] == 3
    summary = execution.summarize(list(files.values()))
    assert (summary["verified_complete"], summary["never_verified"]) == (1, 0)


def test_a_file_without_any_readable_receipt_shows_no_total_instead_of_zero():
    case_id = uuid4()
    rows = [_row(case_id, "Tahsilat makbuzu", date(2026, 1, 1))]
    files = execution.build_files(rows, {rows[0]["document_id"]: "metin yok"})
    assert files[0]["receipts"]["tahsilat"] == {"count": 1, "read": 0, "total": None}
    assert execution.summarize(files)["tahsilat"] == {"count": 1, "read": 0, "total": None}


# --- Gerçek RLS'li veritabanı --------------------------------------------------------------------------------------------


def _world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(execution, "authenticated_database_connection", as_user)
    return db


def _case_with_document(world, owner, court, doc_type, *, source="uyap-avukat-eklentisi"):
    case_id, document_id = uuid4(), uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, '2025/1', '2025/1', %s, 'x')",
        (case_id, owner, court),
    )
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source, doc_type, doc_date) "
        "VALUES (%s, %s, %s, 'm.pdf', %s, %s, %s, '2026-01-05')",
        (document_id, owner, case_id, f"{owner}/{document_id}", source, doc_type),
    )
    return case_id, document_id


def _index(world, owner, document_id, text):
    doc_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO documents (id, project_id, uploaded_by, file_name, mime_type, storage_key, storage_bucket, status, "
        "office_case_document_id) VALUES (%s, NULL, %s, 'm.pdf', 'application/pdf', %s, 'office', 'ready', %s)",
        (doc_id, owner, f"{owner}/{document_id}", document_id),
    )
    world.connection.execute(
        "INSERT INTO document_chunks (id, document_id, chunk_index, content, content_hash, metadata) "
        "VALUES (%s, %s, 0, %s, %s, '{}'::jsonb)", (uuid4(), doc_id, text, uuid4().hex),
    )


@needs_db
def test_only_the_owners_execution_files_are_listed_and_non_execution_cases_are_left_out(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    mine, document = _case_with_document(world, world.alice, "Ankara 7. Genel İcra Dairesi", "Tahsilat makbuzu")
    _index(world, world.alice, document, "Tutar 100,00 TL\n(*) 100,00 TL")
    _case_with_document(world, world.alice, "Ankara 5. Sulh Hukuk Mahkemesi", "Takip Talebi")  # icra değil
    theirs, _ = _case_with_document(world, world.bob, "İstanbul İcra Dairesi", "Takip Talebi")

    result = execution.execution_files(world.alice)

    assert [item["case_id"] for item in result["files"]] == [mine]
    assert result["files"][0]["receipts"]["tahsilat"] == {"count": 1, "read": 1, "total": "100.00"}
    assert result["summary"]["files"] == 1
    assert [item["case_id"] for item in execution.execution_files(world.bob)["files"]] == [theirs]

    # Doğrulama kaydı yalnız sahibinin listesinde görünür.
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_uyap_case_sync (case_id, owner_id, dosya_durumu, found_count, server_documents, complete) "
        "VALUES (%s, %s, 'Açık', 1, 1, true)", (mine, world.alice),
    )
    listed = execution.execution_files(world.alice)
    assert listed["files"][0]["uyap"]["durum"] == "Açık" and listed["files"][0]["uyap"]["complete"] is True
    assert listed["summary"]["verified_complete"] == 1
    assert execution.execution_files(world.bob)["files"][0]["uyap"] is None


@needs_db
def test_trashed_documents_and_unindexed_receipts_do_not_break_the_list(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    case_id, trashed = _case_with_document(world, world.alice, "Ankara İcra Dairesi", "Takip Talebi")
    world.become(None)
    world.connection.execute("UPDATE office_case_documents SET deleted_at = now() WHERE id = %s", (trashed,))
    other, _ = _case_with_document(world, world.alice, "Ankara 2. İcra Dairesi", "Tahsilat makbuzu")  # metni okunmamış

    files = execution.execution_files(world.alice)["files"]

    assert [item["case_id"] for item in files] == [other]  # çöpteki tek evrakı olan dosya listede yok
    assert files[0]["receipts"]["tahsilat"] == {"count": 1, "read": 0, "total": None}


def test_detail_summary_passes_uyaps_account_fields_through_without_computing_anything():
    from datetime import datetime, timezone

    stamp = datetime(2026, 10, 6, tzinfo=timezone.utc)
    assert execution._detail_info({"detail_fetched_at": None}) is None  # çekilmemiş
    info = execution._detail_info({
        "detail_fetched_at": stamp, "detail_complete": True,
        "account_pairs": [{"label": "Toplam Alacak", "value": "13.783,00 TL"}, {"label": "", "value": "x"}, "bozuk", {"label": "Yatan Para", "value": "2.000,00 TL"}],
    })
    assert info == {"complete": True, "fetched_at": stamp, "account": [
        {"label": "Toplam Alacak", "value": "13.783,00 TL"}, {"label": "Yatan Para", "value": "2.000,00 TL"}]}
    # Hesap sekmesi olmayan (ör. icra hukuk mahkemesi) dosyada özet boş hesapla gelir.
    assert execution._detail_info({"detail_fetched_at": stamp, "detail_complete": False, "account_pairs": None})["account"] == []


@needs_db
def test_the_execution_list_carries_the_stored_account_summary_only_for_the_owner(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    mine, _ = _case_with_document(world, world.alice, "Ankara 7. Genel İcra Dairesi", "Takip Talebi")
    world.become(None)
    tabs = (
        '[{"key": "bilgiler", "label": "Dosya Bilgileri", "pairs": [{"label": "Türü", "value": "x"}], "tables": [], "complete": true},'
        ' {"key": "hesap", "label": "Dosya Hesabı", "pairs": [{"label": "Toplam Alacak", "value": "13.783,00 TL"},'
        ' {"label": "Bakiye Borç Miktari", "value": "11.783,00 TL"}], "tables": [], "complete": true}]'
    )
    world.connection.execute(
        "INSERT INTO office_uyap_case_detail (case_id, owner_id, tabs, complete) VALUES (%s, %s, %s::jsonb, true)", (mine, world.alice, tabs),
    )

    detail = execution.execution_files(world.alice)["files"][0]["detail"]
    assert detail["complete"] is True
    assert detail["account"] == [{"label": "Toplam Alacak", "value": "13.783,00 TL"}, {"label": "Bakiye Borç Miktari", "value": "11.783,00 TL"}]
    other, _ = _case_with_document(world, world.bob, "İstanbul İcra Dairesi", "Takip Talebi")
    assert execution.execution_files(world.bob)["files"][0]["detail"] is None  # başkasının dosya hesabı sızmaz
