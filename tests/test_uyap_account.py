"""Dosyalar kimin UYAP'ından geldiyse onun altında durur: bir hesapta birden çok UYAP kişisi, evrak başına işaret
(gerçek RLS'li veritabanında)."""

from __future__ import annotations

import contextlib
from uuid import UUID, uuid4

import pytest

from api import uyap_account
from api.uyap_account import UyapIdentity
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)


def _identity(fingerprint: str, kind: str = "tc", display: str = "Ayşe Yılmaz") -> UyapIdentity:
    return UyapIdentity(fingerprint=fingerprint * 64, kind=kind, portal="vatandas", display=display)


@pytest.fixture
def world(db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("UYAP_IDENTITY_SECRET", "test-secret-for-uyap-identity")

    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(uyap_account, "authenticated_database_connection", as_user)
    return db


def _document(world, owner, esas="2024/1", birim="Ankara 1. Asliye Hukuk Mahkemesi", source="uyap-avukat-eklentisi") -> UUID:
    world.become(None)
    document_id = uuid4()
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, file_name, storage_path, source, uyap_file_no, uyap_birim) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (document_id, owner, f"{document_id}.pdf", f"{owner}/{document_id}.pdf", source, esas, birim),
    )
    return document_id


def test_the_identity_digest_is_keyed_and_never_the_raw_fingerprint(monkeypatch):
    monkeypatch.setenv("UYAP_IDENTITY_SECRET", "one-secret-value-123")
    identity = _identity("a")
    first = uyap_account.identity_digest(identity)
    assert first != identity.fingerprint and len(first) == 64
    monkeypatch.setenv("UYAP_IDENTITY_SECRET", "another-secret-456")
    assert uyap_account.identity_digest(identity) != first  # sunucu anahtarı olmadan parmak izinden eşleştirilemez


@pytest.mark.parametrize("display", ["12345678901", "Ayşe 1234", "<b>Ayşe</b>", ""])
def test_a_display_name_cannot_carry_digits_or_markup(display):
    with pytest.raises(Exception):
        _identity("a", display=display)


@needs_db
def test_several_uyap_people_can_feed_one_account_and_each_is_registered_once(world):
    first = uyap_account.register(world.alice, _identity("a", display="Ayşe Yılmaz"))
    second = uyap_account.register(world.alice, _identity("b", display="Mehmet Kaya"))
    assert first != second
    assert uyap_account.register(world.alice, _identity("a", display="AYŞE YILMAZ")) == first  # ad tazelenir, kimlik aynı
    world.become(world.alice)
    names = [r["display_name"] for r in world.connection.execute("SELECT display_name FROM office_uyap_accounts ORDER BY created_at")]
    assert names == ["AYŞE YILMAZ", "Mehmet Kaya"]
    world.become(None)
    events = world.connection.execute(
        "SELECT metadata FROM activity_logs WHERE action = 'office.uyap_account_added' AND actor_user_id = %s", (world.alice,)
    ).fetchall()
    assert len(events) == 2 and events[0]["metadata"] == {"kind": "tc", "portal": "vatandas"}  # ad/parmak izi yazılmaz


@needs_db
def test_the_same_person_in_two_jurisai_accounts_is_two_separate_private_records(world):
    alice_account = uyap_account.register(world.alice, _identity("a"))
    bob_account = uyap_account.register(world.bob, _identity("a"))
    assert alice_account != bob_account
    world.become(world.bob)
    assert [r["id"] for r in world.connection.execute("SELECT id FROM office_uyap_accounts")] == [bob_account]


@needs_db
def test_documents_are_marked_once_and_only_unattributed_ones_of_that_file(world):
    first = uyap_account.register(world.alice, _identity("a"))
    second = uyap_account.register(world.alice, _identity("b", display="Mehmet Kaya"))
    in_file = _document(world, world.alice)
    same_file_spaced = _document(world, world.alice, esas="2024 / 1", birim="ankara 1. asliye hukuk  mahkemesi")
    other_file = _document(world, world.alice, esas="2024/2")
    assert uyap_account.mark(world.alice, first, esas_no="2024/1", birim="Ankara 1. Asliye Hukuk Mahkemesi") == 2
    assert uyap_account.mark(world.alice, second, esas_no="2024/1", birim="Ankara 1. Asliye Hukuk Mahkemesi") == 0  # el değiştirmez
    assert uyap_account.mark(world.alice, second, document_id=other_file) == 1
    world.become(None)
    marks = {r["id"]: r["uyap_account_id"] for r in world.connection.execute(
        "SELECT id, uyap_account_id FROM office_case_documents WHERE id = ANY(%s)", ([in_file, same_file_spaced, other_file],))}
    assert marks == {in_file: first, same_file_spaced: first, other_file: second}


@needs_db
def test_a_document_cannot_be_marked_with_another_owners_uyap_person(world):
    bobs = uyap_account.register(world.bob, _identity("c"))
    document = _document(world, world.alice)
    world.become(None)
    with pytest.raises(Exception):
        with world.connection.transaction():
            world.connection.execute("UPDATE office_case_documents SET uyap_account_id = %s WHERE id = %s", (bobs, document))


@needs_db
def test_the_account_list_counts_files_per_person_and_unattributed_uyap_documents(world):
    from api.uyap_account import list_accounts

    first = uyap_account.register(world.alice, _identity("a"))
    uyap_account.mark(world.alice, first, document_id=_document(world, world.alice))
    _document(world, world.alice, esas="2023/9")  # kimden geldiği bilinmiyor
    _document(world, world.alice, esas=None, birim=None, source="manual")  # UYAP dışı: sayılmaz
    result = list_accounts(world.alice)
    assert [(a["display"], a["files"], a["documents"]) for a in result["accounts"]] == [("Ayşe Yılmaz", 1, 1)]
    assert result["unknown"] == {"files": 1, "documents": 1}


@needs_db
def test_a_person_whose_documents_are_all_in_the_trash_shows_zero_files(world):
    from api.uyap_account import list_accounts

    first = uyap_account.register(world.alice, _identity("a"))
    document = _document(world, world.alice)
    uyap_account.mark(world.alice, first, document_id=document)
    world.become(None)
    world.connection.execute("UPDATE office_case_documents SET deleted_at = now() WHERE id = %s", (document,))
    assert [(a["files"], a["documents"]) for a in list_accounts(world.alice)["accounts"]] == [(0, 0)]
