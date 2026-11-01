"""UYAP eklenti anahtarı düz saklanmaz: yalnız SHA-256 özeti ve gösterim ön eki tutulur."""

from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from api import office, office_public
from tests.test_document_indexing import world  # noqa: F401

db_required = pytest.mark.skipif(
    not os.getenv("NHR_TEST_DATABASE_URL"), reason="Isolated test DB not configured"
)

TOKEN = "jsai_" + "a1b2c3d4e5f6" * 4  # 53 karakter


def test_digest_is_plain_sha256_hex():
    assert office_public.token_digest(TOKEN) == hashlib.sha256(TOKEN.encode()).hexdigest()
    assert len(office_public.token_digest(TOKEN)) == 64


def test_lookup_uses_the_digest_never_the_plain_value(monkeypatch):
    seen: list[tuple] = []

    class _Result:
        def fetchone(self):
            return None

    class _Connection:
        def execute(self, sql, params=()):
            seen.append((sql, params))
            return _Result()

        def commit(self):
            pass

    @contextlib.contextmanager
    def admin():
        yield _Connection()

    monkeypatch.setattr(office_public, "admin_database_connection", admin)

    assert office_public._owner_for_token(TOKEN) is None
    sql, params = seen[0]
    assert "token_hash" in sql and "WHERE token =" not in sql
    assert params == (office_public.token_digest(TOKEN),)
    assert TOKEN not in str(seen)


def test_a_valid_key_whose_owner_lost_access_is_refused_before_anything_is_written(monkeypatch):
    writes: list[str] = []

    class _Result:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class _Connection:
        def execute(self, sql, params=()):
            if sql.lstrip().startswith("SELECT"):
                return _Result({"id": uuid4(), "owner_id": uuid4(), "revoked": False})
            writes.append(sql)
            return _Result(None)

        def commit(self):
            pass

    @contextlib.contextmanager
    def admin():
        yield _Connection()

    monkeypatch.setattr(office_public, "admin_database_connection", admin)
    monkeypatch.setattr(office_public, "user_allowed", lambda connection, owner_id: False)
    with pytest.raises(office_public.OwnerAccessDenied):
        office_public._owner_for_token(TOKEN)
    assert writes == []  # son kullanım zamanı bile yazılmaz


def test_generic_office_route_cannot_write_the_digest_columns():
    assert {"token_hash", "token_prefix"} <= office._TABLE_PROTECTED_COLUMNS["uyap_ingest_tokens"]


def test_migration_and_init_are_identical_and_leave_no_plain_tokens():
    migration = Path("database/migrations/033_uyap_token_hash.sql").read_text(encoding="utf-8")
    assert migration == Path("database/init/034_uyap_token_hash.sql").read_text(encoding="utf-8")
    assert "SET token = NULL" in migration and "sha256(" in migration


def _insert(connection, owner, token):
    connection.execute("RESET ROLE")
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(owner),))
    token_id = uuid4()
    connection.execute(
        "INSERT INTO office_uyap_ingest_tokens (id, owner_id, token, label) VALUES (%s, %s, %s, 'test')",
        (token_id, owner, token),
    )
    return token_id


@db_required
def test_plain_value_is_replaced_by_its_digest_on_insert(world):  # noqa: F811
    connection, alice, _bob, _files, _current = world
    token_id = _insert(connection, alice, TOKEN)

    row = connection.execute(
        "SELECT token, token_hash, token_prefix, revoked FROM office_uyap_ingest_tokens WHERE id = %s",
        (token_id,),
    ).fetchone()

    assert row["token"] is None  # düz değer hiçbir yerde kalmaz
    assert row["token_hash"] == office_public.token_digest(TOKEN)
    assert row["token_prefix"] == TOKEN[:9] and row["revoked"] is False
    found = connection.execute(
        "SELECT id FROM office_uyap_ingest_tokens WHERE token_hash = %s",
        (office_public.token_digest(TOKEN),),
    ).fetchone()
    assert found["id"] == token_id


@db_required
def test_weak_tokens_are_rejected(world):  # noqa: F811
    connection, alice, *_ = world
    with pytest.raises(psycopg.Error):
        with connection.transaction():
            _insert(connection, alice, "kisa-anahtar")


@db_required
def test_token_value_cannot_be_changed_or_made_readable_again_but_can_be_revoked(world):  # noqa: F811
    connection, alice, *_ = world
    token_id = _insert(connection, alice, TOKEN)
    for column, value in (
        ("token", "jsai_" + "z" * 40),
        ("token_hash", "0" * 64),
        ("token_prefix", "hileli"),
    ):
        with pytest.raises(psycopg.Error):
            with connection.transaction():
                connection.execute(
                    f"UPDATE office_uyap_ingest_tokens SET {column} = %s WHERE id = %s",
                    (value, token_id),
                )
    connection.execute("UPDATE office_uyap_ingest_tokens SET revoked = true WHERE id = %s", (token_id,))
    assert connection.execute(
        "SELECT revoked FROM office_uyap_ingest_tokens WHERE id = %s", (token_id,)
    ).fetchone()["revoked"]


@db_required
def test_other_users_cannot_see_the_token_row(world):  # noqa: F811
    connection, alice, bob, *_ = world
    token_id = _insert(connection, alice, TOKEN)
    connection.execute("RESET ROLE")
    connection.execute("SET LOCAL ROLE nhr_runtime")
    connection.execute("SELECT set_config('app.user_id', %s, true)", (str(bob),))
    assert (
        connection.execute(
            "SELECT 1 FROM office_uyap_ingest_tokens WHERE id = %s", (token_id,)
        ).fetchone()
        is None
    )
