"""Denetim günlüğü: olay yazımı, hata politikası ve içerik sızdırmama.

Veritabanı gerektirmez; bağlantılar sahtelenir.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import audit, conversations, documents, projects
from api.ai import pipeline as ai_pipeline
from api.ai.verification import VerifiedAnswer
from api.audit import AuditContext, email_fingerprint, record_event
from api.auth import routes as auth_routes
from api.auth.routes import current_user_id
from api.auth.security import create_access_token
from api.schemas import AIAnswerRequest
from tests.factories import court_decision_context

USER_ID = uuid4()
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
SECRET = "s" * 40


class FakeConnection:
    """execute çağrılarını kaydeder; INSERT INTO activity_logs olaylarını ayrıca toplar."""

    def __init__(self, handler=None, *, fail_audit=False, login_failures=0):
        self.handler = handler or (lambda sql, params: None)
        self.fail_audit = fail_audit
        self.login_failures = login_failures
        self.calls: list[tuple[str, object]] = []
        self.events: list[dict] = []
        self.savepoints = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "INSERT INTO activity_logs" in sql:
            if self.fail_audit:
                raise psycopg.errors.OperationalError("denetim tablosu yok")
            keys = ("id", "actor", "action", "entity_type", "entity_id", "project_id",
                    "request_id", "ip", "user_agent", "metadata")
            event = dict(zip(keys, params))
            event["metadata"] = event["metadata"].obj  # Jsonb sarmalayıcısı
            self.events.append(event)
            return _Result(None)
        if "_access_allowed(" in sql:
            # Erişim listesi (migration 062) bu testlerin konusu değil: herkes girer.
            return _Result({"allowed": True})
        if "FROM activity_logs" in sql and "email_ip_failures" in sql:
            # Giriş sınırlaması toplu bir sorgudur ve gerçekte her zaman tek satır döner.
            return _Result({"email_ip_failures": self.login_failures, "ip_failures": self.login_failures})
        return _Result(self.handler(sql, params))

    @contextmanager
    def transaction(self):
        self.savepoints += 1
        yield

    @contextmanager
    def cursor(self):
        connection = self

        class Cursor:
            def executemany(self, sql, rows):
                connection.calls.append((sql, list(rows)))

        yield Cursor()


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value if not isinstance(self.value, list) else None

    def fetchall(self):
        return self.value if isinstance(self.value, list) else []

    @property
    def rowcount(self):
        return self.value if isinstance(self.value, int) else 0


def _context():
    return AuditContext(request_id=uuid4(), ip_address="203.0.113.7", user_agent="pytest-agent")


# --- bağlam ve yardımcılar -----------------------------------------------------------


def _request(host, headers=None):
    return SimpleNamespace(
        client=SimpleNamespace(host=host) if host else None,
        headers=headers or {},
    )


def test_context_keeps_valid_ip_and_clips_user_agent():
    context = AuditContext.from_request(_request("203.0.113.7", {"user-agent": "x" * 900}))

    assert context.ip_address == "203.0.113.7"
    assert len(context.user_agent) == 300
    assert isinstance(context.request_id, UUID)


def test_context_drops_non_ip_client_and_ignores_forwarded_header():
    forged = {"x-forwarded-for": "10.9.9.9"}

    assert AuditContext.from_request(_request("testclient", forged)).ip_address is None
    assert AuditContext.from_request(_request("203.0.113.7", forged)).ip_address == "203.0.113.7"
    assert AuditContext.from_request(_request(None)).ip_address is None


def test_email_fingerprint_is_stable_short_and_hides_the_address():
    fingerprint = email_fingerprint("  Avukat@Ornek.COM ")

    assert fingerprint == email_fingerprint("avukat@ornek.com")
    assert len(fingerprint) == 16
    assert "avukat" not in fingerprint and "ornek" not in fingerprint


# --- record_event ------------------------------------------------------------------


def test_record_event_inserts_with_app_generated_id_and_no_returning():
    connection = FakeConnection()

    record_event(
        connection,
        action="project.create",
        actor_user_id=USER_ID,
        context=_context(),
        entity_type="project",
        entity_id=uuid4(),
        metadata={"matter_type": "case"},
    )

    sql = connection.calls[0][0]
    assert "INSERT INTO activity_logs" in sql and "RETURNING" not in sql.upper()
    event = connection.events[0]
    assert isinstance(event["id"], UUID)
    assert event["actor"] == USER_ID and event["action"] == "project.create"
    assert event["ip"] == "203.0.113.7" and event["user_agent"] == "pytest-agent"
    assert event["metadata"] == {"matter_type": "case"}
    assert connection.savepoints == 0  # strict: savepoint yok, iş transaction'ına dahil


def test_strict_audit_failure_propagates_so_no_unaudited_write_remains():
    connection = FakeConnection(fail_audit=True)

    with pytest.raises(psycopg.Error):
        record_event(connection, action="project.create", actor_user_id=USER_ID)


def test_best_effort_audit_failure_is_swallowed_inside_a_savepoint():
    connection = FakeConnection(fail_audit=True)

    record_event(connection, action="ai.answer", actor_user_id=USER_ID, strict=False)

    assert connection.savepoints == 1


def test_standalone_never_raises(monkeypatch):
    @contextmanager
    def broken():
        raise RuntimeError("DATABASE_ADMIN_URL tanımlı değil")
        yield

    monkeypatch.setattr(audit, "admin_database_connection", broken)

    audit.record_event_standalone(action="auth.login_failed")  # istisna sızmamalı


# --- projeler / belgeler / sohbet silme ---------------------------------------------


def _client(router, monkeypatch, module, connection):
    @contextmanager
    def fake_auth(user_id: str):
        assert user_id == str(USER_ID)
        yield connection

    monkeypatch.setattr(module, "authenticated_database_connection", fake_auth)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user_id] = lambda: USER_ID
    return TestClient(app)


def _project_row():
    return {
        "id": uuid4(), "name": "Dosya", "description": None, "matter_type": "case", "status": "active",
        "reference_no": None, "court_name": None, "chamber": None, "docket_no": None, "opened_on": None,
        "member_role": "owner", "document_count": 0, "created_at": NOW, "updated_at": NOW,
    }


def test_project_creation_is_audited_in_the_same_transaction(monkeypatch):
    connection = FakeConnection(lambda sql, params: _project_row() if "SELECT" in sql else None)
    client = _client(projects.router, monkeypatch, projects, connection)

    response = client.post("/api/projects", json={"name": "Gizli müvekkil davası"})

    assert response.status_code == 201
    event = connection.events[0]
    inserted_project_id = next(
        params[0] for sql, params in connection.calls if "INSERT INTO projects" in sql
    )
    assert event["action"] == "project.create" and event["actor"] == USER_ID
    assert event["entity_id"] == inserted_project_id == event["project_id"]
    assert "Gizli müvekkil davası" not in json.dumps(event["metadata"])  # ad yazılmaz


def test_project_creation_fails_when_the_audit_cannot_be_written(monkeypatch):
    connection = FakeConnection(fail_audit=True)
    client = _client(projects.router, monkeypatch, projects, connection)

    assert client.post("/api/projects", json={"name": "Dosya adı"}).status_code == 503


def test_document_upload_is_audited_without_file_name_or_content(monkeypatch, tmp_path):
    def handler(sql, params):
        if "FROM documents" in sql:
            return {
                "id": uuid4(), "project_id": None, "file_name": "gizli-dilekce.txt", "mime_type": "text/plain",
                "file_size": 10, "status": "ready", "processing_error": None, "chunk_count": 1,
                "created_at": NOW, "processed_at": NOW,
            }
        return None

    connection = FakeConnection(handler)
    monkeypatch.setattr(
        documents, "get_settings",
        lambda: SimpleNamespace(max_document_size_bytes=1024 * 1024, document_storage_dir=str(tmp_path)),
    )
    client = _client(documents.router, monkeypatch, documents, connection)
    content = ("Müvekkilin gizli kıdem tazminatı talebi hakkında örnek metin. " * 5).encode()

    response = client.post(
        "/api/documents", files={"file": ("gizli-dilekce.txt", content, "text/plain")}
    )

    assert response.status_code == 201
    event = connection.events[0]
    assert event["action"] == "document.upload" and event["entity_type"] == "document"
    assert event["metadata"]["extension"] == ".txt"
    assert event["metadata"]["file_size"] == len(content)
    assert event["metadata"]["chunk_count"] >= 1
    serialized = json.dumps(event["metadata"], ensure_ascii=False)
    assert "gizli" not in serialized and "Müvekkil" not in serialized


def test_conversation_delete_is_audited_only_when_something_was_deleted(monkeypatch):
    conversation_id = uuid4()
    hit = FakeConnection(lambda sql, params: 1)
    client = _client(conversations.router, monkeypatch, conversations, hit)
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert hit.events[0]["action"] == "conversation.delete"
    assert hit.events[0]["entity_id"] == conversation_id

    miss = FakeConnection(lambda sql, params: 0)
    client = _client(conversations.router, monkeypatch, conversations, miss)
    assert client.delete(f"/api/conversations/{uuid4()}").status_code == 404
    assert miss.events == []


# --- AI cevabı ----------------------------------------------------------------------


def test_ai_answer_audit_has_counts_but_never_the_question_or_answer(monkeypatch):
    connection = FakeConnection()
    conversation_id, message_id = uuid4(), uuid4()

    @contextmanager
    def fake_auth(user_id: str):
        yield connection

    monkeypatch.setattr(ai_pipeline, "authenticated_database_connection", fake_auth)
    monkeypatch.setattr(ai_pipeline, "record_exchange", lambda *args, **kwargs: (conversation_id, message_id))
    secret_question = "Müvekkil Ali Veli kıdem tazminatı alabilir mi?"
    request = AIAnswerRequest(question=secret_question, project_id=uuid4())
    answer = VerifiedAnswer(
        text="Ali Veli alabilir. [K1]", contexts=(court_decision_context(),), unverified_markers=()
    )

    ids = ai_pipeline.persist_answer(
        request, answer, user_id=USER_ID, model_name="qwen", audit=_context(), from_cache=True
    )

    assert ids == (conversation_id, message_id)
    event = connection.events[0]
    assert event["action"] == "ai.answer" and event["actor"] == USER_ID
    assert event["entity_id"] == conversation_id and event["project_id"] == request.project_id
    assert event["metadata"]["grounded"] is True and event["metadata"]["from_cache"] is True
    assert event["metadata"]["citation_count"] == 1
    serialized = json.dumps(event["metadata"], ensure_ascii=False)
    assert "Ali Veli" not in serialized and "kıdem" not in serialized
    assert connection.savepoints == 1  # best-effort: denetim hatası cevabı düşürmez


def test_ai_answer_survives_an_audit_failure(monkeypatch):
    connection = FakeConnection(fail_audit=True)

    @contextmanager
    def fake_auth(user_id: str):
        yield connection

    conversation_id, message_id = uuid4(), uuid4()
    monkeypatch.setattr(ai_pipeline, "authenticated_database_connection", fake_auth)
    monkeypatch.setattr(ai_pipeline, "record_exchange", lambda *args, **kwargs: (conversation_id, message_id))
    answer = VerifiedAnswer(text="Cevap [K1]", contexts=(court_decision_context(),), unverified_markers=())

    ids = ai_pipeline.persist_answer(
        AIAnswerRequest(question="Kıdem tazminatı şartları nelerdir?"),
        answer, user_id=USER_ID, model_name="qwen",
    )

    assert ids == (conversation_id, message_id)


# --- kimlik doğrulama ---------------------------------------------------------------


def _user_row(*, status="active"):
    return {
        "id": USER_ID, "email": "avukat@ornek.com", "full_name": "Ayşe Yılmaz", "status": status,
        "created_at": NOW, "password_hash": "hash", "roles": ["lawyer"],
    }


@pytest.fixture
def auth(monkeypatch):
    standalone: list[dict] = []
    monkeypatch.setattr(
        auth_routes, "get_settings",
        lambda: SimpleNamespace(jwt_secret=SECRET, jwt_expire_minutes=5, auth_cookie_secure=False, allow_registration=True),
    )
    monkeypatch.setattr(auth_routes, "record_event_standalone", lambda **kwargs: standalone.append(kwargs))
    app = FastAPI()
    app.include_router(auth_routes.router)
    return SimpleNamespace(client=TestClient(app), standalone=standalone, monkeypatch=monkeypatch)


def _use_admin_connection(monkeypatch, connection):
    @contextmanager
    def fake_admin():
        yield connection

    monkeypatch.setattr(auth_routes, "admin_database_connection", fake_admin)


def _login(auth, *, row, password_ok=True, email="Avukat@Ornek.com"):
    connection = FakeConnection(lambda sql, params: row if "FROM users" in sql else None)
    _use_admin_connection(auth.monkeypatch, connection)
    auth.monkeypatch.setattr(auth_routes, "verify_password", lambda password, hashed: password_ok)
    response = auth.client.post("/api/auth/login", json={"email": email, "password": "gizli-parola-123"})
    return response, connection


def test_successful_login_is_audited_with_the_user_id(auth):
    response, connection = _login(auth, row=_user_row())

    assert response.status_code == 200
    event = connection.events[0]
    assert event["action"] == "auth.login" and event["actor"] == USER_ID
    assert auth.standalone == []


def test_failed_login_is_audited_without_email_or_password(auth):
    response, connection = _login(auth, row=_user_row(), password_ok=False)

    assert response.status_code == 401
    assert connection.events == []  # başarısızlık ayrı bağlantıyla yazılır (transaction geri alınmasın)
    logged = auth.standalone[0]
    assert logged["action"] == "auth.login_failed" and logged.get("actor_user_id") is None
    assert logged["metadata"]["reason"] == "invalid_credentials"
    assert logged["metadata"]["email_fingerprint"] == email_fingerprint("avukat@ornek.com")
    dump = json.dumps(logged, default=str)
    assert "ornek.com" not in dump and "gizli-parola" not in dump


def test_login_failure_responses_are_identical_for_unknown_wrong_and_inactive(auth):
    unknown, _ = _login(auth, row=None)
    wrong, _ = _login(auth, row=_user_row(), password_ok=False)
    inactive, _ = _login(auth, row=_user_row(status="suspended"))

    assert {unknown.status_code, wrong.status_code, inactive.status_code} == {401}
    assert unknown.json() == wrong.json() == inactive.json()
    assert [entry["metadata"]["reason"] for entry in auth.standalone] == [
        "invalid_credentials", "invalid_credentials", "account_inactive",
    ]


def test_login_still_succeeds_when_the_audit_table_is_unavailable(auth):
    connection = FakeConnection(lambda sql, params: _user_row() if "FROM users" in sql else None, fail_audit=True)
    _use_admin_connection(auth.monkeypatch, connection)
    auth.monkeypatch.setattr(auth_routes, "verify_password", lambda password, hashed: True)

    response = auth.client.post("/api/auth/login", json={"email": "avukat@ornek.com", "password": "x"})

    assert response.status_code == 200


def test_registration_is_audited_without_email_or_name(auth):
    connection = FakeConnection(lambda sql, params: _user_row() if "INSERT INTO users" in sql else None)
    _use_admin_connection(auth.monkeypatch, connection)
    auth.monkeypatch.setattr(auth_routes, "hash_password", lambda password: "hash")

    response = auth.client.post(
        "/api/auth/register",
        json={"email": "yeni@ornek.com", "password": "yeterince-uzun-parola", "full_name": "Yeni Kullanıcı", "terms_accepted": True, "terms_version": "test"},
    )

    assert response.status_code == 201
    event = connection.events[0]
    assert event["action"] == "auth.register" and event["actor"] == USER_ID
    assert "yeni@ornek" not in json.dumps(event["metadata"]) and "Yeni Kullanıcı" not in json.dumps(event["metadata"])


def test_logout_is_audited_only_for_a_signed_in_user(auth):
    token, _ = create_access_token(user_id=USER_ID, secret=SECRET, expires_minutes=5)

    signed_in = auth.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    anonymous = auth.client.post("/api/auth/logout")  # oturumsuz

    # Çıkış gerçekten bir HTTP yanıtı döndürmeli (durum kodu boş kalırsa sunucu bağlantıyı keser,
    # kullanıcı hiç çıkış yapamaz) ve oturum çerezini silmeli.
    for response in (signed_in, anonymous):
        assert response.status_code == 204 and response.content == b""
        assert "nhr_access_token=" in response.headers["set-cookie"]
        assert "Max-Age=0" in response.headers["set-cookie"]

    assert len(auth.standalone) == 1
    assert auth.standalone[0]["action"] == "auth.logout"
    assert auth.standalone[0]["actor_user_id"] == USER_ID


def test_throttled_login_never_tests_the_password_or_extends_the_lock(auth):
    connection = FakeConnection(
        lambda sql, params: _user_row() if "FROM users" in sql else None,
        login_failures=auth_routes.LOGIN_MAX_FAILURES_PER_EMAIL_IP,
    )
    _use_admin_connection(auth.monkeypatch, connection)
    tested: list[str] = []
    auth.monkeypatch.setattr(
        auth_routes, "verify_password", lambda password, hashed: tested.append(password) or True
    )

    response = auth.client.post("/api/auth/login", json={"email": "avukat@ornek.com", "password": "dogru-parola-123"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == str(auth_routes.LOGIN_WINDOW_MINUTES * 60)
    assert tested == []  # kilitli istemci doğru parolayı bile sınayamaz
    assert auth.standalone == [] and connection.events == []  # kilit kendini uzatmaz
    assert not any("FROM users" in sql for sql, _ in connection.calls)  # kullanıcı bile aranmaz
