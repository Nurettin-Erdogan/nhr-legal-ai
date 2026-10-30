"""Hesap işlemleri: kayıt onayı, parola değiştirme, şifre sıfırlama ve hesabın silinmesi (KVKK)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from api import account, audit, mailer
from api.auth import routes as auth_routes
from api.auth.security import hash_password, verify_password
from api.main import app
from tests.test_case_document_rag import _case, _indexed_document, db, needs_db  # noqa: F401  (fixture)

OLD_PASSWORD = "eski-parola-12345"
NEW_PASSWORD = "yeni-parola-67890"
REQUEST = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"})


# --- Veritabanı gerektirmeyenler -----------------------------------------------------------------------------------------


def test_registration_requires_accepting_the_terms():
    client = TestClient(app)
    response = client.post("/api/auth/register", json={"email": "yeni@example.com", "password": "yeterince-uzun-parola", "full_name": "Yeni Kullanıcı"})
    assert response.status_code == 400 and "kabul etmelisiniz" in response.json()["detail"]


def test_reset_link_points_at_the_web_app_and_token_is_only_stored_hashed():
    link = account.reset_link("abc123")
    assert link.endswith("/sifre-sifirla?token=abc123") and link.startswith("http")
    assert len(account.token_digest("abc123")) == 64 and "abc123" not in account.token_digest("abc123")


def test_mailer_reports_missing_configuration_instead_of_pretending(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_FROM"):
        monkeypatch.delenv(key, raising=False)
    assert mailer.is_configured() is False
    with pytest.raises(mailer.MailError):
        mailer.send_mail("kisi@example.com", "konu", "metin")


def test_account_endpoints_require_a_session():
    client = TestClient(app)
    assert client.post("/api/account/password", json={"current_password": "x", "new_password": NEW_PASSWORD}).status_code == 401
    assert client.post("/api/account/delete", json={"confirm": account.DELETE_PHRASE}).status_code == 401
    assert client.post("/api/account/profile", json={"full_name": "Ad Soyad"}).status_code == 401


# --- Gerçek veritabanı ---------------------------------------------------------------------------------------------------


@pytest.fixture
def world(db, monkeypatch, tmp_path):  # noqa: F811
    @contextlib.contextmanager
    def admin():
        db.become(None)
        # Gerçek yönetici bağlantısı yeni açılır ve kullanıcı kimliği taşımaz; test tek bağlantıyı paylaştığından önceki
        # `become(kullanıcı)` ayarı temizlenir (aksi halde kullanıcı satırı koruma tetikleyicisi yönetici işlemini engeller).
        db.connection.execute("SELECT set_config('app.user_id', '', true)")
        yield db.connection

    for module in (account, auth_routes, audit):
        monkeypatch.setattr(module, "admin_database_connection", admin)
    monkeypatch.setattr(auth_routes, "_auth_secret", lambda: "t" * 40)
    monkeypatch.setattr(account, "get_settings", lambda: SimpleNamespace(document_storage_dir=str(tmp_path), cors_origins=("http://localhost:3000",)))
    for key in ("SMTP_HOST", "SMTP_FROM", "WEB_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    db.become(None)
    db.connection.execute("UPDATE users SET password_hash = %s, email = %s WHERE id = %s", (hash_password(OLD_PASSWORD), "alice@example.com", db.alice))
    db.tmp = tmp_path
    return db


def _password_hash(world, user):
    world.become(None)
    return world.connection.execute("SELECT password_hash FROM users WHERE id = %s", (user,)).fetchone()["password_hash"]


@needs_db
def test_password_change_needs_the_current_password_and_issues_a_fresh_session(world):
    with pytest.raises(HTTPException) as wrong:
        account.change_password(account.PasswordChangeRequest(current_password="yanlis-parola-000", new_password=NEW_PASSWORD), Response(), REQUEST, world.alice)
    assert wrong.value.status_code == 403 and verify_password(OLD_PASSWORD, _password_hash(world, world.alice))

    response = Response()
    result = account.change_password(account.PasswordChangeRequest(current_password=OLD_PASSWORD, new_password=NEW_PASSWORD), response, REQUEST, world.alice)
    assert result.user.id == world.alice and "nhr_access_token" in response.headers.get("set-cookie", "")
    assert verify_password(NEW_PASSWORD, _password_hash(world, world.alice))
    world.become(None)
    stamp = world.connection.execute("SELECT sessions_valid_after FROM users WHERE id = %s", (world.alice,)).fetchone()["sessions_valid_after"]
    assert stamp is not None  # diğer oturumlar kapatıldı
    actions = [row["action"] for row in world.connection.execute("SELECT action FROM activity_logs WHERE actor_user_id = %s", (world.alice,)).fetchall()]
    assert account.PASSWORD_CHANGE in actions and account.PASSWORD_CHANGE_FAILED in actions


@needs_db
def test_repeated_wrong_current_passwords_are_throttled(world):
    for _ in range(account.MAX_FAILURES):
        with pytest.raises(HTTPException) as wrong:
            account.change_password(account.PasswordChangeRequest(current_password="yanlis-parola-000", new_password=NEW_PASSWORD), Response(), REQUEST, world.alice)
        assert wrong.value.status_code == 403
    with pytest.raises(HTTPException) as locked:
        account.change_password(account.PasswordChangeRequest(current_password=OLD_PASSWORD, new_password=NEW_PASSWORD), Response(), REQUEST, world.alice)
    assert locked.value.status_code == 429 and "dakika" in locked.value.detail


@needs_db
def test_reset_token_works_once_and_expires(world):
    world.become(None)
    token = account.create_reset_token(world.connection, world.alice)
    stored = world.connection.execute("SELECT token_hash FROM auth_password_resets WHERE user_id = %s", (world.alice,)).fetchone()["token_hash"]
    assert stored == account.token_digest(token) and token not in stored

    with pytest.raises(HTTPException) as bad:
        account.confirm_reset(account.ResetConfirm(token="x" * 30, new_password=NEW_PASSWORD), REQUEST)
    assert bad.value.status_code == 400 and verify_password(OLD_PASSWORD, _password_hash(world, world.alice))

    assert account.confirm_reset(account.ResetConfirm(token=token, new_password=NEW_PASSWORD), REQUEST).status_code == 204
    assert verify_password(NEW_PASSWORD, _password_hash(world, world.alice))
    with pytest.raises(HTTPException):  # aynı bağlantı ikinci kez kullanılamaz
        account.confirm_reset(account.ResetConfirm(token=token, new_password="baska-parola-11111"), REQUEST)

    world.become(None)
    expired = account.create_reset_token(world.connection, world.alice)
    world.connection.execute("UPDATE auth_password_resets SET expires_at = %s WHERE token_hash = %s", (datetime.now(timezone.utc) - timedelta(minutes=1), account.token_digest(expired)))
    with pytest.raises(HTTPException):
        account.confirm_reset(account.ResetConfirm(token=expired, new_password="baska-parola-11111"), REQUEST)


@needs_db
def test_reset_request_never_reveals_whether_the_account_exists(world, monkeypatch):
    # E-posta yapılandırılmamış: bağlantı üretilmez, yanıt "manual" der (hesap olsa da olmasa da aynı).
    known = account.request_reset(account.ResetRequest(email="alice@example.com"), REQUEST)
    unknown = account.request_reset(account.ResetRequest(email="yok@example.com"), REQUEST)
    assert known == unknown == {"ok": True, "delivery": "manual"}
    world.become(None)
    assert world.connection.execute("SELECT count(*) AS n FROM auth_password_resets").fetchone()["n"] == 0

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, body)))
    known = account.request_reset(account.ResetRequest(email="alice@example.com"), REQUEST)
    unknown = account.request_reset(account.ResetRequest(email="yok@example.com"), REQUEST)
    assert known == unknown == {"ok": True, "delivery": "email"}
    assert len(sent) == 1 and sent[0][0] == "alice@example.com" and "/sifre-sifirla?token=" in sent[0][1]
    # Denetim kaydında e-posta düz yazılmaz.
    world.become(None)
    rows = world.connection.execute("SELECT metadata::text AS m FROM activity_logs WHERE action = %s", (account.PASSWORD_RESET_REQUEST,)).fetchall()
    assert rows and all("alice@example.com" not in row["m"] for row in rows)


@needs_db
def test_deleting_an_account_erases_its_data_and_files_but_nothing_of_other_users(world):
    alice_case = _case(world, world.alice, "Alice davası")
    bob_case = _case(world, world.bob, "Bob davası")
    alice_doc = _indexed_document(world, world.alice, alice_case, "Davacı işçi kıdem tazminatı talep etmektedir.")
    bob_doc = _indexed_document(world, world.bob, bob_case, "Kiracı kira bedelini ödemiştir.")
    world.become(None)
    conversation = uuid4()
    world.connection.execute("INSERT INTO conversations (id, created_by, title) VALUES (%s, %s, 'sohbet')", (conversation, world.alice))
    world.connection.execute("INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'gizli soru')", (conversation,))
    world.connection.execute("INSERT INTO office_reminders (id, owner_id, title, remind_at) VALUES (%s, %s, 'ara', now())", (uuid4(), world.alice))
    alice_entry, bob_entry = uuid4(), uuid4()
    world.connection.execute(
        "INSERT INTO access_allowlist (id, email) VALUES (%s, 'alice@example.com'), (%s, 'bob-liste@example.com')",
        (alice_entry, bob_entry))
    folder = world.tmp / "office" / str(world.alice)
    folder.mkdir(parents=True)
    (folder / "belge.pdf").write_bytes(b"%PDF")
    other = world.tmp / "office" / str(world.bob)
    other.mkdir(parents=True)
    (other / "belge.pdf").write_bytes(b"%PDF")

    with pytest.raises(HTTPException) as phrase:
        account.delete_account(account.DeleteRequest(password=OLD_PASSWORD, confirm="sil"), REQUEST, world.alice)
    assert phrase.value.status_code == 400
    with pytest.raises(HTTPException) as wrong:
        account.delete_account(account.DeleteRequest(password="yanlis-parola-000", confirm=account.DELETE_PHRASE), REQUEST, world.alice)
    assert wrong.value.status_code == 403
    world.become(None)
    assert world.connection.execute("SELECT count(*) AS n FROM office_cases WHERE owner_id = %s", (world.alice,)).fetchone()["n"] == 1  # hiçbir şey silinmedi

    response = account.delete_account(account.DeleteRequest(password=OLD_PASSWORD, confirm=account.DELETE_PHRASE), REQUEST, world.alice)
    assert response.status_code == 204 and "nhr_access_token" in response.headers.get("set-cookie", "")

    world.become(None)
    count = lambda sql, *params: world.connection.execute(sql, params).fetchone()["n"]  # noqa: E731
    assert count("SELECT count(*) AS n FROM office_cases WHERE owner_id = %s", world.alice) == 0
    assert count("SELECT count(*) AS n FROM office_case_documents WHERE owner_id = %s", world.alice) == 0
    assert count("SELECT count(*) AS n FROM documents WHERE uploaded_by = %s", world.alice) == 0
    assert count("SELECT count(*) AS n FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE d.office_case_document_id = %s", alice_doc) == 0
    assert count("SELECT count(*) AS n FROM conversations WHERE created_by = %s", world.alice) == 0
    assert count("SELECT count(*) AS n FROM messages WHERE conversation_id = %s", conversation) == 0
    assert count("SELECT count(*) AS n FROM office_reminders WHERE owner_id = %s", world.alice) == 0
    assert count("SELECT count(*) AS n FROM access_allowlist WHERE id = %s", alice_entry) == 0  # listedeki e-posta da gider
    user = world.connection.execute("SELECT email, full_name, password_hash, status, deleted_at FROM users WHERE id = %s", (world.alice,)).fetchone()
    assert user["email"].endswith("@deleted.invalid") and user["full_name"] is None and user["password_hash"] is None
    assert user["status"] == "inactive" and user["deleted_at"] is not None
    assert not folder.exists()
    # Başka kullanıcının hiçbir şeyi etkilenmedi.
    assert count("SELECT count(*) AS n FROM office_cases WHERE owner_id = %s", world.bob) == 1
    assert count("SELECT count(*) AS n FROM documents WHERE office_case_document_id = %s", bob_doc) == 1
    assert count("SELECT count(*) AS n FROM access_allowlist WHERE id = %s", bob_entry) == 1
    assert (other / "belge.pdf").exists()
    # Denetim kaydı kimliksiz iz bırakır: e-posta ya da ad yazılmaz.
    log = world.connection.execute("SELECT metadata::text AS m FROM activity_logs WHERE action = %s AND actor_user_id = %s", (account.ACCOUNT_DELETE, world.alice)).fetchone()
    assert log is not None and "alice@example.com" not in log["m"]


@needs_db
def test_profile_name_can_be_changed_but_not_blank(world):
    updated = account.update_profile(account.ProfileRequest(full_name="  Ayşe   Demir "), REQUEST, world.alice)
    assert updated.full_name == "Ayşe Demir"
    with pytest.raises(Exception):
        account.ProfileRequest(full_name="A")
