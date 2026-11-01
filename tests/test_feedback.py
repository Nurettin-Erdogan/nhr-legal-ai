"""Pilot geri bildirimi: kullanıcı yalnız kendi mesajlarını görür, değiştiremez, kategori ve uzunluk denetlenir."""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured")


@pytest.fixture
def world():
    connection = psycopg.connect(os.environ["NHR_TEST_DATABASE_URL"], row_factory=psycopg.rows.dict_row)
    alice, bob = uuid4(), uuid4()
    try:
        for user in (alice, bob):
            connection.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, 'x', 'Test')", (user, f"{user}@test.invalid"))

        def become(user):
            connection.execute("RESET ROLE")
            if user:
                connection.execute("SET LOCAL ROLE nhr_runtime")
                connection.execute("SELECT set_config('app.user_id', %s, true)", (str(user),))

        yield connection, alice, bob, become
    finally:
        connection.rollback()
        connection.close()


def _send(connection, owner, message="Arama çok yavaş", category="hata", page="/dashboard/ai"):
    connection.execute("INSERT INTO office_feedback (id, owner_id, category, page, message) VALUES (%s, %s, %s, %s, %s)", (uuid4(), owner, category, page, message))


def test_a_user_sees_only_their_own_feedback_and_cannot_edit_or_forge_it(world):
    connection, alice, bob, become = world
    become(alice)
    _send(connection, alice)
    become(bob)
    assert connection.execute("SELECT * FROM office_feedback").fetchall() == []  # başkasının mesajı görünmez
    assert connection.execute("UPDATE office_feedback SET message = 'x' WHERE true").rowcount == 0
    assert connection.execute("DELETE FROM office_feedback WHERE true").rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        _send(connection, alice)  # başkası adına gönderilemez
    become(alice)
    [row] = connection.execute("SELECT message, category FROM office_feedback").fetchall()
    assert row["message"] == "Arama çok yavaş"


def test_category_and_length_are_enforced_by_the_database(world):
    connection, alice, _, become = world
    become(alice)
    for kwargs in ({"category": "şikayet"}, {"message": "ab"}, {"message": "x" * 4001}, {"page": "p" * 201}):
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            _send(connection, alice, **kwargs)
    _send(connection, alice, message="Çok iyi çalışıyor", category="begeni")


def test_feedback_is_part_of_the_users_backup_and_export_lists():
    from api.office import TABLES
    from scripts.backup_user_data import USER_TABLES

    assert TABLES["feedback"] == "office_feedback" and "office_feedback" in USER_TABLES
