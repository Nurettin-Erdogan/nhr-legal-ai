"""Sohbet geçmişi uç noktaları. Bağlantı sahtelenir; veritabanı gerekmez."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import conversations
from api.auth.routes import current_user_id
from api.conversations import citation_verification, router

USER_ID = uuid4()
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def _client(monkeypatch, handler):
    """`handler(sql, params)` sorgu sonucunu döndürür: liste (fetchall) ya da dict/None."""
    executed: list[tuple[str, object]] = []

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchall(self):
            return self.value if isinstance(self.value, list) else []

        def fetchone(self):
            return self.value if not isinstance(self.value, list) else None

        @property
        def rowcount(self):
            return self.value if isinstance(self.value, int) else 0

    class Connection:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            return Result(handler(sql, params))

    @contextmanager
    def fake_auth(user_id: str):
        assert user_id == str(USER_ID)  # sorgular oturum kullanıcısının kimliğiyle açılır
        yield Connection()

    monkeypatch.setattr(conversations, "authenticated_database_connection", fake_auth)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_user_id] = lambda: USER_ID
    return TestClient(app), executed


def test_requires_login():
    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    assert client.get("/api/conversations").status_code == 401
    assert client.delete(f"/api/conversations/{uuid4()}").status_code == 401


def test_list_returns_summaries_and_can_filter_by_project(monkeypatch):
    project_id = uuid4()
    row = {
        "id": uuid4(),
        "title": "Kıdem tazminatı",
        "project_id": project_id,
        "created_at": NOW,
        "last_message_at": NOW,
        "message_count": 4,
    }
    client, executed = _client(monkeypatch, lambda sql, params: [row])

    everything = client.get("/api/conversations")
    filtered = client.get(f"/api/conversations?project_id={project_id}")

    assert everything.status_code == 200
    assert everything.json()[0]["title"] == "Kıdem tazminatı"
    assert everything.json()[0]["message_count"] == 4
    assert "conversation.project_id = %(project_id)s" not in executed[0][0]
    assert "conversation.project_id = %(project_id)s" in executed[1][0]
    assert executed[1][1]["project_id"] == project_id


def test_list_limit_is_bounded(monkeypatch):
    client, _ = _client(monkeypatch, lambda sql, params: [])

    assert client.get("/api/conversations?limit=101").status_code == 422
    assert client.get("/api/conversations?limit=0").status_code == 422


def test_list_supports_exact_case_and_office_project_filters_and_rejects_mixing(monkeypatch):
    client, executed = _client(monkeypatch, lambda sql, params: [])
    for name in ('case_id', 'office_project_id'):
        value = uuid4()
        assert client.get(f'/api/conversations?{name}={value}').status_code == 200
        assert f'conversation.{name} = %({name})s' in executed[-1][0]
        assert executed[-1][1][name] == value
    assert client.get(f'/api/conversations?case_id={uuid4()}&office_project_id={uuid4()}').status_code == 422


def _detail_handler(conversation_id, message_id, citation_rows, *, missing=False):
    def handler(sql, params):
        if "FROM conversations" in sql:
            return None if missing else {
                "id": conversation_id,
                "title": "Kıdem tazminatı",
                "project_id": None,
                "created_at": NOW,
            }
        if "FROM messages" in sql:
            return [
                {
                    "id": uuid4(), "role": "user", "content": "Soru?",
                    "model_name": None, "metadata": {}, "created_at": NOW,
                },
                {
                    "id": message_id, "role": "assistant", "content": "Cevap. [K1]",
                    "model_name": "qwen", "created_at": NOW,
                    "metadata": {"grounded": True, "unverified_markers": ["K3"]},
                },
            ]
        if "FROM citations" in sql:
            return citation_rows
        raise AssertionError(sql)

    return handler


def _citation(message_id, *, method, status, document_chunk_id=None):
    return {
        "message_id": message_id,
        "citation_order": 1,
        "marker": "K1",
        "source_title": "Yargıtay 9. Hukuk Dairesi, E. 2023/1, K. 2024/2",
        "source_locator": {
            "source_id": str(uuid4()),
            "source_type": "court_decision",
            "source_url": "https://example.test/k/1",
        },
        "snippet": "Kıdem tazminatına hak kazanılır.",
        "document_chunk_id": document_chunk_id,
        "ingestion_method": method,
        "ingest_status": status,
    }


def test_detail_returns_messages_with_citations_and_current_verification(monkeypatch):
    conversation_id, message_id = uuid4(), uuid4()
    citations = [_citation(message_id, method="bulk_seed", status="pending")]
    client, _ = _client(monkeypatch, _detail_handler(conversation_id, message_id, citations))

    response = client.get(f"/api/conversations/{conversation_id}")

    assert response.status_code == 200
    body = response.json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assistant = body["messages"][1]
    assert assistant["grounded"] is True
    assert assistant["unverified_markers"] == ["K3"]
    assert assistant["citations"][0]["marker"] == "K1"
    assert assistant["citations"][0]["verification"] == "third_party"
    assert UUID(assistant["citations"][0]["source_id"])
    assert body["messages"][0]["citations"] == []
    assert body["messages"][0]["grounded"] is None


def test_detail_shows_official_after_a_seed_was_verified(monkeypatch):
    conversation_id, message_id = uuid4(), uuid4()
    citations = [_citation(message_id, method="yargitay_public_json_http", status="ready")]
    client, _ = _client(monkeypatch, _detail_handler(conversation_id, message_id, citations))

    citation = client.get(f"/api/conversations/{conversation_id}").json()["messages"][1]["citations"][0]

    assert citation["verification"] == "official"


def test_detail_of_unknown_or_hidden_conversation_is_404(monkeypatch):
    client, _ = _client(
        monkeypatch, _detail_handler(uuid4(), uuid4(), [], missing=True)
    )

    assert client.get(f"/api/conversations/{uuid4()}").status_code == 404


def test_delete_soft_deletes_with_the_acting_user(monkeypatch):
    conversation_id = uuid4()
    client, executed = _client(monkeypatch, lambda sql, params: 1)

    response = client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 204
    assert "deleted_at = NOW()" in executed[0][0]
    assert executed[0][1] == (USER_ID, conversation_id)


def test_delete_of_missing_conversation_is_404(monkeypatch):
    client, _ = _client(monkeypatch, lambda sql, params: 0)

    assert client.delete(f"/api/conversations/{uuid4()}").status_code == 404


def test_citation_verification_labels():
    assert citation_verification(
        document_chunk_id=uuid4(), ingestion_method=None, ingest_status=None
    ) == "user_document"
    assert citation_verification(
        document_chunk_id=None, ingestion_method="bulk_seed", ingest_status="pending"
    ) == "third_party"
    assert citation_verification(
        document_chunk_id=None, ingestion_method="bulk_seed", ingest_status="ready"
    ) == "official"
    assert citation_verification(
        document_chunk_id=None, ingestion_method=None, ingest_status=None
    ) == "third_party"


def test_quarantined_or_missing_source_is_never_official():
    for state in (None, "failed", "quarantined", "pending"):
        assert citation_verification(
            document_chunk_id=None, ingestion_method="bulk_seed", ingest_status=state
        ) == "third_party"
