"""Genel büro ucunda müvekkil, dava ve proje kaydının sunucu tarafı doğrulaması (veritabanı gerektirmez)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.office import _validate_prepared


@pytest.mark.parametrize(
    ("table", "row"),
    [
        ("clients", {"full_name": "Ayşe Yılmaz", "client_type": "individual", "email": "a@b.co", "national_id": "10000000146"}),
        ("clients", {"full_name": "ABC A.Ş.", "client_type": "corporate", "tax_id": "1234567890"}),
        ("cases", {"title": "İşçilik Alacağı", "status": "pending", "case_no": "2026/1"}),
        ("projects", {"name": "Proje", "color": "#C8A24B"}),
    ],
)
def test_valid_rows_pass(table, row):
    _validate_prepared(table, row, insert=True)


@pytest.mark.parametrize(
    ("table", "row", "message"),
    [
        ("clients", {"full_name": "  "}, "boş"),
        ("clients", {"full_name": "A" * 201}, "200"),
        ("clients", {"full_name": "A", "client_type": "uzayli"}, "tipi"),
        ("clients", {"full_name": "A", "email": "not-an-email"}, "e-posta"),
        ("clients", {"full_name": "A", "national_id": "1234567890"}, "11 haneli"),
        ("clients", {"full_name": "A", "tax_id": "12"}, "Vergi"),
        ("cases", {"title": ""}, "boş"),
        ("cases", {"title": "X", "status": "bogus"}, "durum"),
        ("cases", {"title": "T" * 301}, "300"),
        ("projects", {"name": "P", "color": "javascript:alert(1)"}, "renk"),
    ],
)
def test_invalid_rows_are_rejected_with_a_turkish_message(table, row, message):
    with pytest.raises(HTTPException) as caught:
        _validate_prepared(table, row, insert=True)
    assert caught.value.status_code == 400
    assert message.lower() in caught.value.detail.lower()


def test_update_only_validates_the_fields_it_changes():
    _validate_prepared("cases", {"status": "closed"}, insert=False)
    with pytest.raises(HTTPException):
        _validate_prepared("cases", {"title": " "}, insert=False)


def test_other_tables_are_not_restricted():
    _validate_prepared("project_notes", {"title": ""}, insert=True)


def test_document_rows_must_point_into_the_owners_own_storage_folder():
    from uuid import uuid4

    owner = uuid4()
    _validate_prepared("case_documents", {"file_name": "a.txt", "storage_path": f"{owner}/abc-a.txt"}, insert=True, user_id=owner)
    for bad in (f"{uuid4()}/a.txt", "../../etc/passwd", f"{owner}/../x", "tek-parca"):
        with pytest.raises(HTTPException) as caught:
            _validate_prepared("case_documents", {"file_name": "a.txt", "storage_path": bad}, insert=True, user_id=owner)
        assert caught.value.status_code == 400
    with pytest.raises(HTTPException):
        _validate_prepared("case_documents", {"file_name": " ", "storage_path": f"{owner}/a"}, insert=True, user_id=owner)


def test_storage_file_names_reject_unsafe_characters_and_excess_length():
    from api.office import _validate_file_key

    _validate_file_key("u/abc-sözleşme (1).docx")
    for bad in ("u/<script>.html", 'u/a"b.txt', "u/" + "a" * 201, "u/", "u/zararli.exe", "u/uzantisiz"):
        with pytest.raises(HTTPException) as caught:
            _validate_file_key(bad)
        assert caught.value.status_code == 400


@pytest.mark.parametrize(
    ("table", "row"),
    [
        ("tasks", {"title": "Dilekçe hazırla", "status": "todo", "priority": "urgent"}),
        ("calendar_events", {"title": "Duruşma", "event_type": "hearing"}),
        ("reminders", {"title": "Ara", "channel": "email", "status": "pending"}),
    ],
)
def test_valid_agenda_rows_pass(table, row):
    _validate_prepared(table, row, insert=True)


@pytest.mark.parametrize(
    ("table", "row", "message"),
    [
        ("tasks", {"title": " "}, "boş"),
        ("tasks", {"title": "T" * 301}, "300"),
        ("tasks", {"title": "X", "status": "bogus"}, "status"),
        ("tasks", {"title": "X", "priority": "acil-acil"}, "priority"),
        ("calendar_events", {"title": "X", "event_type": "uzayli"}, "event_type"),
        ("reminders", {"title": "X", "channel": "sms"}, "channel"),
    ],
)
def test_invalid_agenda_rows_are_rejected(table, row, message):
    with pytest.raises(HTTPException) as caught:
        _validate_prepared(table, row, insert=True)
    assert caught.value.status_code == 400
    assert message in str(caught.value.detail)


def test_event_cannot_end_before_it_starts_and_partial_updates_are_checked():
    from datetime import datetime, timezone

    start = datetime(2026, 12, 1, 10, tzinfo=timezone.utc)
    with pytest.raises(HTTPException):
        _validate_prepared("calendar_events", {"title": "X", "start_at": start, "end_at": datetime(2026, 12, 1, 9, tzinfo=timezone.utc)}, insert=True)
    with pytest.raises(HTTPException):
        _validate_prepared("tasks", {"title": ""}, insert=False)
    _validate_prepared("tasks", {"status": "done"}, insert=False)  # kısmi güncelleme başlığı zorunlu kılmaz
