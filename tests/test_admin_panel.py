"""Platform yönetici paneli (2026-10-24): yalnız yönetici, içerik değil sayı, kendini kilitleme yok, kayıt modu ve davetler."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin_ingestion, admin_panel, registration
from api.auth.routes import current_user_id

ADMIN_ID = uuid4()
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")
db_required = pytest.mark.skipif(not DATABASE_URL, reason="Isolated test DB not configured")


class FakeConnection:
    """Records SQL; answers the admin check and a few panel queries."""

    def __init__(self, *, admin: bool, rows=None, user_exists=True):
        self.admin, self.rows, self.user_exists = admin, rows or [], user_exists
        self.queries: list[str] = []

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, sql, params=None):
        self.queries.append(sql)
        outer = self

        class Result:
            rowcount = 1

            def fetchone(self):
                if "app_has_global_role" in sql:
                    return {"is_admin": outer.admin}
                if "SELECT status FROM users" in sql:
                    return {"status": "active"} if outer.user_exists else None
                if "FROM users" in sql:
                    return {"x": 1} if outer.user_exists else None
                return {}

            def fetchall(self):
                return outer.rows

        return Result()


def _client(monkeypatch, connection, revoked=None):
    @contextmanager
    def fake_auth(user_id: str):
        yield connection

    monkeypatch.setattr(admin_ingestion, "authenticated_database_connection", fake_auth)
    monkeypatch.setattr(admin_panel, "authenticated_database_connection", fake_auth)
    monkeypatch.setattr(admin_panel, "revoke_sessions", lambda user_id: (revoked if revoked is not None else []).append(user_id))
    app = FastAPI()
    app.include_router(admin_panel.router)
    app.dependency_overrides[current_user_id] = lambda: ADMIN_ID
    return TestClient(app)


def _user_row(**overrides):
    row = {"user_id": uuid4(), "email": "avukat@example.test", "full_name": "Ayşe Avukat", "status": "active",
           "created_at": NOW, "last_login_at": NOW, "roles": ["lawyer"], "cases": 3, "clients": 2, "documents": 40,
           "conversations": 5, "ai_answers_30d": 12, "last_activity_at": NOW}
    row.update(overrides)
    return row


@pytest.mark.parametrize("method,path,body", [
    ("get", "/api/admin/overview", None),
    ("get", "/api/admin/users", None),
    ("post", f"/api/admin/users/{uuid4()}/status", {"status": "suspended"}),
    ("post", f"/api/admin/users/{uuid4()}/roles/admin", None),
    ("delete", f"/api/admin/users/{uuid4()}/roles/lawyer", None),
    ("get", "/api/admin/feedback", None),
    ("get", "/api/admin/registration", None),
    ("post", "/api/admin/registration", {"mode": "invite"}),
    ("post", "/api/admin/registration/invites", {"email": "yeni@example.test"}),
    ("delete", f"/api/admin/registration/invites/{uuid4()}", None),
])
def test_every_admin_endpoint_refuses_a_non_admin(monkeypatch, method, path, body):
    connection = FakeConnection(admin=False)
    client = _client(monkeypatch, connection)
    response = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert response.status_code == 403
    assert all("app_has_global_role" in sql for sql in connection.queries)  # nothing but the role check ran


def test_users_list_filters_by_text_and_status_and_carries_only_counts(monkeypatch):
    rows = [_user_row(), _user_row(email="baska@example.test", full_name="Mehmet", status="suspended")]
    client = _client(monkeypatch, FakeConnection(admin=True, rows=rows))
    body = client.get("/api/admin/users?q=ayşe").json()
    assert [row["email"] for row in body] == ["avukat@example.test"]
    assert set(body[0]) == set(admin_panel.UserRow.model_fields)  # account data and counts, no case/document content
    assert [r["email"] for r in client.get("/api/admin/users?status=suspended").json()] == ["baska@example.test"]


def test_an_admin_cannot_lock_themselves_out(monkeypatch):
    client = _client(monkeypatch, FakeConnection(admin=True))
    assert client.post(f"/api/admin/users/{ADMIN_ID}/status", json={"status": "suspended"}).status_code == 400
    assert client.delete(f"/api/admin/users/{ADMIN_ID}/roles/admin").status_code == 400


def test_suspending_closes_open_sessions_and_is_audited(monkeypatch):
    revoked: list = []
    connection = FakeConnection(admin=True)
    client = _client(monkeypatch, connection, revoked)
    target = uuid4()
    response = client.post(f"/api/admin/users/{target}/status", json={"status": "suspended"})
    assert response.status_code == 200 and revoked == [target]
    assert any("UPDATE users SET status" in sql for sql in connection.queries)
    assert any("INSERT INTO activity_logs" in sql for sql in connection.queries)
    revoked.clear()
    assert client.post(f"/api/admin/users/{target}/status", json={"status": "active"}).status_code == 200
    assert revoked == []  # re-activation does not need to close anything


def test_an_unknown_user_or_role_is_refused(monkeypatch):
    client = _client(monkeypatch, FakeConnection(admin=True, user_exists=False))
    assert client.post(f"/api/admin/users/{uuid4()}/status", json={"status": "suspended"}).status_code == 404
    assert client.post(f"/api/admin/users/{uuid4()}/roles/superuser").status_code == 422


def test_the_last_backup_is_read_from_its_manifest(tmp_path, monkeypatch):
    folder = tmp_path / "jurisai-20261024-154350"
    folder.mkdir()
    (folder / "manifest.json").write_text('{"created_at": "2026-10-24T15:43:50+03:00", "tables": {"users": 2, "x": 3},'
                                          ' "dump": {"bytes": 10}}', encoding="utf-8")
    (tmp_path / "jurisai-20261025-010000").mkdir()  # an unfinished run without a manifest is skipped
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    backup = admin_panel._last_backup()
    assert backup == {"found": True, "created_at": "2026-10-24T15:43:50+03:00", "rows": 5, "database_bytes": 10,
                      "uploads_included": False}


def test_corpus_counts_are_read_from_the_real_statistics_model(monkeypatch):
    # Mevzuat sayısı yanlış alandan okunuyor, panelde hep "—" görünüyordu (2026-10-24).
    from api import legal
    from api.schemas import CorpusStats

    stats = CorpusStats(source_count=12, chunk_count=40, decision_count=7, legislation_count=3,
                        latest_decision_date=None, seed_count=2)
    monkeypatch.setattr(legal, "corpus_stats", lambda: stats)
    corpus = admin_panel._corpus()
    assert (corpus["decisions"], corpus["legislation"], corpus["pending_verification"]) == (7, 3, 2)


def test_the_init_copy_matches_the_migration():
    migration = Path("database/migrations/062_admin_panel.sql").read_text(encoding="utf-8")
    assert migration == Path("database/init/063_admin_panel.sql").read_text(encoding="utf-8")
    assert migration.count("PERFORM public.admin_require();") == 3
    assert "ENABLE ROW LEVEL SECURITY" in migration and "REVOKE DELETE, TRUNCATE" in migration


# --- Gerçek veritabanı: erişim kuralları ve kayıt kapısı ---------------------------------------------------------------

@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _user(conn, label: str, role: str = "lawyer"):
    user_id = uuid4()
    conn.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES (%s, %s, 'x', %s)",
                 (user_id, f"{label}-{user_id.hex[:8]}@example.test", label))
    conn.execute("INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE code = %s", (user_id, role))
    return user_id


@contextmanager
def _as(conn, user_id):
    """The application role with one user's session, undone afterwards."""
    with conn.transaction():
        conn.execute("SET LOCAL ROLE nhr_runtime")
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        yield conn
        raise psycopg.Rollback


@db_required
def test_admin_functions_refuse_a_lawyer_and_return_counts_to_an_admin(connection):  # noqa: F811
    admin = _user(connection, "yonetici", "admin")
    lawyer = _user(connection, "avukat")
    connection.execute("INSERT INTO office_feedback (owner_id, category, message) VALUES (%s, 'hata', 'Arama yavaş')",
                       (lawyer,))
    for function in ("admin_user_overview()", "admin_platform_summary()", "admin_feedback_list(10, NULL)"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), _as(connection, lawyer):
            connection.execute(f"SELECT * FROM {function}").fetchall()
    with _as(connection, admin):
        rows = {row["user_id"]: row for row in connection.execute("SELECT * FROM admin_user_overview()").fetchall()}
        assert rows[lawyer]["roles"] == ["lawyer"] and rows[admin]["roles"] == ["admin"]
        assert isinstance(rows[lawyer]["documents"], int)
        feedback = connection.execute("SELECT * FROM admin_feedback_list(10, 'hata')").fetchall()
        assert any(item["user_id"] == lawyer and item["message"] == "Arama yavaş" for item in feedback)
        summary = connection.execute("SELECT * FROM admin_platform_summary()").fetchone()
        assert summary["users_total"] >= 2 and summary["feedback_total"] >= 1


@db_required
def test_only_an_admin_reads_or_writes_registration_settings_and_invites(connection):  # noqa: F811
    admin = _user(connection, "yonetici", "admin")
    lawyer = _user(connection, "avukat")
    with _as(connection, lawyer):
        assert connection.execute("SELECT * FROM platform_settings").fetchall() == []
        assert connection.execute("SELECT * FROM registration_invites").fetchall() == []
    with pytest.raises(psycopg.errors.InsufficientPrivilege), _as(connection, lawyer):
        connection.execute("INSERT INTO registration_invites (id, email) VALUES (%s, 'x@example.test')", (uuid4(),))
    with _as(connection, admin):
        connection.execute("INSERT INTO registration_invites (id, email, invited_by) VALUES (%s, 'x@example.test', %s)",
                           (uuid4(), admin))
        assert connection.execute("SELECT value FROM platform_settings WHERE key = 'registration_mode'").fetchone()
    with pytest.raises(psycopg.errors.InsufficientPrivilege), _as(connection, admin):
        connection.execute("DELETE FROM registration_invites")  # invites are revoked, never deleted


@db_required
def test_registration_modes_and_single_use_invites(connection, monkeypatch):  # noqa: F811
    monkeypatch.setattr(registration, "get_settings", lambda: SimpleNamespace(allow_registration=True))
    connection.execute("UPDATE platform_settings SET value = 'invite' WHERE key = 'registration_mode'")
    with pytest.raises(registration.RegistrationClosed):
        registration.registration_gate(connection, "davetsiz@example.test")
    invite_id = uuid4()
    connection.execute("INSERT INTO registration_invites (id, email) VALUES (%s, 'davetli@example.test')", (invite_id,))
    assert registration.registration_gate(connection, "Davetli@Example.test") == invite_id
    new_user = _user(connection, "davetli")
    registration.consume_invite(connection, invite_id, new_user)
    with pytest.raises(registration.RegistrationClosed):  # the same invite cannot open a second account
        registration.registration_gate(connection, "davetli@example.test")
    connection.execute("UPDATE platform_settings SET value = 'closed' WHERE key = 'registration_mode'")
    with pytest.raises(registration.RegistrationClosed):
        registration.registration_gate(connection, "kimse@example.test")
    connection.execute("UPDATE platform_settings SET value = 'open' WHERE key = 'registration_mode'")
    assert registration.registration_gate(connection, "herkes@example.test") is None
    monkeypatch.setattr(registration, "get_settings", lambda: SimpleNamespace(allow_registration=False))
    with pytest.raises(registration.RegistrationClosed):  # the deployment switch always wins
        registration.registration_gate(connection, "herkes@example.test")


@db_required
def test_an_admin_can_suspend_a_lawyer_but_a_lawyer_cannot_change_status(connection):  # noqa: F811
    admin = _user(connection, "yonetici", "admin")
    lawyer = _user(connection, "avukat")
    with pytest.raises(psycopg.errors.RaiseException), _as(connection, lawyer):
        connection.execute("UPDATE users SET status = 'inactive' WHERE id = %s", (lawyer,))
    with _as(connection, admin):
        connection.execute("UPDATE users SET status = 'suspended' WHERE id = %s", (lawyer,))
        assert connection.execute("SELECT status FROM users WHERE id = %s", (lawyer,)).fetchone()["status"] == "suspended"
