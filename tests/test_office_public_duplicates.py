"""UYAP belge yineleme denetimi gerçek RLS'li veritabanında; yazdıklarını geri alır."""
import os
from uuid import uuid4

import psycopg
import pytest

from api.office_public import find_duplicate

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


@pytest.fixture
def owner_db():
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"])
    alice, bob = uuid4(), uuid4()
    try:
        for user in (alice, bob):
            connection.execute(
                "INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, %s, %s)",
                (user, f"{user}@test.invalid", "not-a-password", "Test"),
            )
        yield connection, alice, bob
    finally:
        connection.rollback()
        connection.close()


def _document(connection, owner, *, name, size, file_no, source="uyap-extension"):
    document_id = uuid4()
    connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, file_name, storage_path, size_bytes, source, uyap_file_no) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (document_id, owner, name, f"{owner}/{document_id}", size, source, file_no),
    )
    return document_id


def _as(connection, user):
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(user),))


def test_same_name_in_a_different_case_is_not_a_duplicate(owner_db):
    connection, alice, _ = owner_db
    first = _document(connection, alice, name="dilekce.pdf", size=100, file_no="2024/1")
    _as(connection, alice)

    same = find_duplicate(connection, file_name="dilekce.pdf", size_bytes=100, uyap_file_no="2024/1", source=None)
    other_case = find_duplicate(connection, file_name="dilekce.pdf", size_bytes=100, uyap_file_no="2024/2", source=None)
    other_size = find_duplicate(connection, file_name="dilekce.pdf", size_bytes=101, uyap_file_no="2024/1", source=None)

    assert same == first
    assert other_case is None
    assert other_size is None


def test_missing_file_number_matches_only_missing_file_number(owner_db):
    connection, alice, _ = owner_db
    unnumbered = _document(connection, alice, name="evrak.pdf", size=5, file_no=None)
    _as(connection, alice)

    assert find_duplicate(connection, file_name="evrak.pdf", size_bytes=5, uyap_file_no=None, source=None) == unnumbered
    assert find_duplicate(connection, file_name="evrak.pdf", size_bytes=5, uyap_file_no="2024/9", source=None) is None


def test_source_filter_and_owner_isolation(owner_db):
    connection, alice, bob = owner_db
    _document(connection, alice, name="a.pdf", size=1, file_no="2024/1", source="uyap-extension")
    _as(connection, alice)
    assert find_duplicate(connection, file_name="a.pdf", size_bytes=1, uyap_file_no="2024/1", source="baska") is None
    assert find_duplicate(connection, file_name="a.pdf", size_bytes=1, uyap_file_no="2024/1", source="uyap-extension")

    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(bob),))
    assert find_duplicate(connection, file_name="a.pdf", size_bytes=1, uyap_file_no="2024/1", source=None) is None
