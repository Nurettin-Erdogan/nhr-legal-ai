from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import bureau_assistant as bureau

NOW = datetime(2026, 10, 25, 15, tzinfo=bureau.ZONE)


def hearing(**updates):
    return dict(id=uuid4(), title="Sentetik dava", status="active", court="Mahkeme",
                case_no="2026/1", next_hearing=NOW + timedelta(days=1), **updates)


def document(**updates):
    return dict(id=uuid4(), file_name="sentetik.pdf", created_at=NOW,
                case_id=None, case_title=None, **updates)


def test_readonly_proposals_are_source_linked_and_never_infer_legal_deadlines():
    h, d = hearing(), document()
    proposals = bureau.proposals([h], [d], [], [], NOW)
    assert [p["kind"] for p in proposals] == ["hearing", "document"]
    assert proposals[0]["date"] == h["next_hearing"].isoformat()
    assert proposals[0]["source_url"].endswith(str(h["id"]))
    assert proposals[1]["case_id"] is None
    assert "süre sonucu çıkarılmadı" in proposals[1]["description"]


def test_expired_closed_existing_calendar_and_handled_records_are_excluded():
    h, d = hearing(), document()
    assert not bureau.proposals([dict(h, status="closed")], [], [], [], NOW)
    assert not bureau.proposals([dict(h, next_hearing=NOW-timedelta(days=1))], [], [], [], NOW)
    assert bureau.proposals([], [dict(d, created_at=NOW-timedelta(days=365))], [], [], NOW)
    assert bureau.proposals([dict(h, next_hearing=NOW+timedelta(days=365))], [], [], [], NOW)
    assert not bureau.proposals([h], [], [], [{"case_id":h["id"],"start_at":h["next_hearing"]}], NOW)
    row = bureau.proposals([], [d], [], [], NOW)[0]
    assert not bureau.proposals([], [d], [{"proposal_key":row["key"]}], [], NOW)


class Connection:
    def __init__(self, previous=None):
        self.previous = previous
        self.calls = []
    def execute(self, sql, params=None):
        self.calls.append((sql,params))
        self.sql = sql
        return self
    def fetchone(self):
        return self.previous if "SELECT status,task_id,event_id" in self.sql else {"id":uuid4()}


@pytest.mark.parametrize("kind", ["document", "hearing"])
def test_approval_uses_server_source_and_application_uuid_no_returning(monkeypatch, kind):
    h, d = hearing(), document()
    proposal = next(p for p in bureau.proposals([h],[d],[],[],NOW) if p["kind"] == kind)
    monkeypatch.setattr(bureau,"snapshot",lambda db,now:{"proposals":[proposal]})
    events = []
    monkeypatch.setattr(bureau,"record_event",lambda *args,**kwargs:events.append(kwargs))
    db, owner = Connection(), uuid4()
    result = bureau.decide(db,owner,bureau.Decision(key=proposal["key"],action="approve",title="Düzenlenmiş başlık"),None,NOW)
    assert result["status"] == "approved"
    inserts = [(sql,p) for sql,p in db.calls if "INSERT INTO office_" in sql]
    assert len(inserts) == 2
    assert all("RETURNING" not in sql for sql,p in inserts)
    assert inserts[0][1][1] == owner
    assert inserts[0][1][3] == "Düzenlenmiş başlık"
    assert "pg_advisory_xact_lock" in db.calls[0][0]
    assert events[0]["strict"] is True


def test_repeat_decision_never_creates_another_record(monkeypatch):
    db = Connection(previous={"status":"approved","task_id":uuid4(),"event_id":None})
    monkeypatch.setattr(bureau,"snapshot",lambda *args:pytest.fail("A repeat must not reapply"))
    result = bureau.decide(db,uuid4(),bureau.Decision(key=f"document:{uuid4()}",action="approve"),None,NOW)
    assert result["repeated"]
    assert not any("INSERT" in sql for sql,p in db.calls)


def test_dismissal_only_records_decision_no_task_or_calendar(monkeypatch):
    proposal = bureau.proposals([], [document()], [], [], NOW)[0]
    monkeypatch.setattr(bureau,"snapshot",lambda *args:{"proposals":[proposal]})
    monkeypatch.setattr(bureau,"record_event",lambda *args,**kwargs:None)
    db = Connection()
    bureau.decide(db,uuid4(),bureau.Decision(key=proposal["key"],action="dismiss"),None,NOW)
    writes = [sql for sql,p in db.calls if "INSERT" in sql]
    assert len(writes) == 1 and "office_bureau_decisions" in writes[0]
    assert not any("DELETE" in sql for sql,p in db.calls)


def test_changed_or_inaccessible_source_cannot_be_approved(monkeypatch):
    monkeypatch.setattr(bureau,"snapshot",lambda *args:{"proposals":[]})
    db = Connection()
    with pytest.raises(HTTPException) as exc:
        bureau.decide(db,uuid4(),bureau.Decision(key=f"document:{uuid4()}",action="approve"),None,NOW)
    assert exc.value.status_code == 409
    assert not any("INSERT" in sql for sql,p in db.calls)


def test_both_endpoints_require_an_authenticated_user():
    app = FastAPI()
    app.include_router(bureau.router)
    client = TestClient(app)
    assert client.get("/api/bureau-assistant").status_code == 401
    assert client.post("/api/bureau-assistant/decisions",json={"key":"x","action":"approve"}).status_code == 401


def test_decision_table_has_forced_owner_rls_and_is_not_generic_crud():
    from api.office import TABLES, EXPORT_ONLY_TABLES
    sql = (Path(__file__).resolve().parents[1]/"database/migrations/063_bureau_assistant.sql").read_text(encoding="utf-8")
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "USING (owner_id = public.app_current_user_id())" in sql
    assert "WITH CHECK (owner_id = public.app_current_user_id())" in sql
    assert "UNIQUE(owner_id, proposal_key)" in sql
    assert "office_bureau_decisions" not in TABLES.values()
    assert "office_bureau_decisions" in EXPORT_ONLY_TABLES.values()


def test_fresh_install_includes_bureau_migration():
    root = Path(__file__).resolve().parents[1]
    init = (root / "database/init/064_bureau_assistant.sql").read_text(encoding="utf-8")
    assert "\\i /nhr-database/migrations/063_bureau_assistant.sql" in init
    assert "ON_ERROR_STOP on" in init


def test_daily_summary_uses_istanbul_calendar_day_and_only_saved_records():
    from datetime import timezone

    class SnapshotConnection:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            self.sql = sql
            return self

        def fetchall(self):
            return []

        def fetchone(self):
            if "AS today_tasks" in self.sql:
                return dict(open_tasks=8, overdue_tasks=2, today_tasks=3)
            return {"count": 4}

    db = SnapshotConnection()
    # UTC Sunday night is already Monday in Istanbul.
    result = bureau.snapshot(db, datetime(2026, 10, 25, 22, tzinfo=timezone.utc))
    assert result["counts"] == dict(open_tasks=8, overdue_tasks=2, today_tasks=3,
                                    today_hearings=4, upcoming_hearings=4)
    sql, params = next((s, p) for s, p in db.calls if "AS today_tasks" in s)
    now, start, end = params
    assert start == datetime(2026, 10, 26, tzinfo=bureau.ZONE)
    assert end == start + timedelta(days=1)
    assert now.hour == 1
    assert "due_date >= %s AND due_date < %s" in sql
    assert all("INSERT" not in s and "UPDATE" not in s for s, _ in db.calls)


def test_review_requires_a_current_owner_visible_proposal(monkeypatch):
    monkeypatch.setattr(bureau, "snapshot", lambda *args: {"proposals": []})
    db = Connection()
    with pytest.raises(HTTPException) as exc:
        bureau.review(db, f"document:{uuid4()}", NOW)
    assert exc.value.status_code == 409
    assert db.calls == []


@pytest.mark.parametrize("kind", ["document", "hearing"])
def test_review_only_reads_source_scoped_documents_and_never_exposes_unready_text(monkeypatch, kind):
    h, d = hearing(), document()
    proposal = next(p for p in bureau.proposals([h], [d], [], [], NOW) if p["kind"] == kind)
    monkeypatch.setattr(bureau, "snapshot", lambda *args: {"proposals": [proposal]})

    class ReviewConnection(Connection):
        def fetchall(self):
            return [dict(id=uuid4(), file_name="Belge.pdf", status="ready" if i else "failed",
                         ocr=bool(i), excerpt="Kaynak metin") for i in range(11)]

    db = ReviewConnection()
    result = bureau.review(db, proposal["key"], NOW)
    assert len(result["documents"]) == 11 and not result["limited"]
    assert result["documents"][0]["excerpt"] is None
    assert result["documents"][0]["ready"] is False
    assert result["documents"][1]["ready"] is True
    assert result["suggested_action"] == proposal["description"]
    sql, params = db.calls[0]
    assert "deleted_at IS NULL" in sql and "LIMIT 11" not in sql
    assert params[0] == (d["id"] if kind == "document" else None)
    assert params[3] == proposal["case_id"]
    assert all("INSERT" not in s and "UPDATE" not in s for s, _ in db.calls)


def test_review_endpoint_requires_authentication_and_bounded_key():
    app = FastAPI()
    app.include_router(bureau.router)
    with TestClient(app) as client:
        assert client.get("/api/bureau-assistant/review", params={"key": "x"}).status_code == 401
        app.dependency_overrides[bureau.current_user_id] = lambda: uuid4()
        assert client.get("/api/bureau-assistant/review", params={"key": "x" * 241}).status_code == 422
