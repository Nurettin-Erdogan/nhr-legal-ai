"""Full UYAP run history: bounded metadata, immutable finals and real owner RLS."""
import contextlib
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import account, account_export, office, uyap_runs
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401
from tests.test_uyap_sync import REQUEST, _case


def checkpoint(**extra):
    reports = []
    for i, outcome in enumerate(["complete", "empty", "incomplete", "failed", "pending"]):
        found = 3 if outcome in {"complete", "incomplete"} else 0
        missing = 1 if outcome == "incomplete" else 0
        reports.append(dict(esas=f"2025/{i+1}", birim="Test Dairesi", outcome=outcome,
                            declared=found, found=found, stored=found-missing, missing=missing,
                            sent=0, pulls=0, problems=[]))
    return uyap_runs.RunCheckpoint(**(dict(id=uuid4(), revision=1, finished=False, verify_only=True,
                                         list_complete=True, reports=reports) | extra))


def test_history_requires_a_session_and_is_exported_but_not_generic_crud():
    client = TestClient(app)
    assert client.get("/api/office/uyap/audit-runs").status_code == 401
    assert client.post("/api/office/uyap/audit-runs", json=checkpoint().model_dump(mode="json")).status_code == 401
    assert office.EXPORT_ONLY_TABLES["uyap_audit_runs"] == "office_uyap_audit_runs"
    assert "uyap_audit_runs" not in office.TABLES


def test_history_is_not_cacheable():
    response = Response()
    uyap_runs._private_history_response(response)
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("change", [
    {"revision": 0}, {"reports": []}, {"token": "secret"},
    {"reports": [dict(esas="2025/1", birim="X", outcome="complete", declared=0, found=0, stored=0, missing=0, sent=0, pulls=0)]},
])
def test_malformed_or_unbounded_claims_are_refused(change):
    with pytest.raises(ValidationError):
        checkpoint(**change)


def test_document_bodies_ephemeral_keys_and_duplicate_files_are_refused():
    row = checkpoint().reports[0].model_dump()
    for extra in [{"key": "ephemeral"}, {"detail": dict(state="complete", tabs=1, saved=True, problems=[], data={"body": "private"})}]:
        with pytest.raises(ValidationError):
            checkpoint(reports=[row | extra])
    with pytest.raises(ValidationError):
        checkpoint(reports=[row, row])


def world(db, monkeypatch):
    @contextlib.contextmanager
    def connection(owner):
        db.become(UUID(owner))
        yield db.connection
    monkeypatch.setattr(uyap_runs, "authenticated_database_connection", connection)
    monkeypatch.setattr(uyap_runs, "record_event", lambda *a, **k: None)
    return db


@needs_db
def test_full_history_round_trips_every_outcome_and_final_cannot_be_rewritten(db, monkeypatch):  # noqa: F811
    w = world(db, monkeypatch)
    _case(w, w.alice, number="2025/1", court="Test Dairesi", documents=3)
    body = checkpoint()
    uyap_runs.save_audit_run(body, w.alice, REQUEST)
    loaded = uyap_runs.load_audit_runs(w.alice)["runs"][0]
    assert loaded["finished"] is False
    assert [r["outcome"] for r in loaded["snapshot"]["reports"]] == ["complete", "empty", "incomplete", "failed", "pending"]
    final = body.model_copy(update={"revision": 2, "finished": True})
    uyap_runs.save_audit_run(final, w.alice, REQUEST)
    for overwrite in [body, final.model_copy(update={"revision": 3})]:
        with pytest.raises(HTTPException) as error:
            uyap_runs.save_audit_run(overwrite, w.alice, REQUEST)
        assert error.value.status_code == 409


@needs_db
def test_report_complete_claims_are_downgraded_when_server_evidence_is_missing(db, monkeypatch):  # noqa: F811
    w = world(db, monkeypatch)
    body = checkpoint()
    body.reports[0].detail = uyap_runs.RunDetail(state="complete", tabs=1, saved=True)
    saved = uyap_runs.save_audit_run(body, w.alice, REQUEST)["snapshot"]["reports"][0]
    assert (saved["outcome"], saved["stored"], saved["missing"]) == ("incomplete", 0, 3)
    assert saved["detail"]["state"] == "failed" and not saved["detail"]["saved"]


@needs_db
def test_other_owner_cannot_read_update_or_delete_report_even_with_direct_sql(db, monkeypatch):  # noqa: F811
    w = world(db, monkeypatch)
    body = checkpoint()
    uyap_runs.save_audit_run(body, w.alice, REQUEST)
    assert uyap_runs.load_audit_runs(w.bob)["runs"] == []
    w.become(w.bob)
    assert w.connection.execute("SELECT id FROM office_uyap_audit_runs WHERE id=%s", (body.id,)).fetchone() is None
    assert w.connection.execute("UPDATE office_uyap_audit_runs SET revision=9 WHERE id=%s", (body.id,)).rowcount == 0
    assert w.connection.execute("DELETE FROM office_uyap_audit_runs WHERE id=%s", (body.id,)).rowcount == 0
    w.become(w.alice)
    assert w.connection.execute("DELETE FROM office_uyap_audit_runs WHERE id=%s", (body.id,)).rowcount == 1


@needs_db
def test_uuid_collision_cannot_overwrite_another_owner_report(db, monkeypatch):  # noqa: F811
    w = world(db, monkeypatch)
    body = checkpoint()
    uyap_runs.save_audit_run(body, w.alice, REQUEST)
    with w.connection.transaction(force_rollback=True):
        with pytest.raises(HTTPException) as error:
            uyap_runs.save_audit_run(body.model_copy(update={"revision": 2}), w.bob, REQUEST)
        assert error.value.status_code == 409


@needs_db
def test_history_is_in_owner_export_and_account_purge_without_touching_other_users(db, monkeypatch):  # noqa: F811
    w = world(db, monkeypatch)
    own, other = checkpoint(), checkpoint()
    uyap_runs.save_audit_run(own, w.alice, REQUEST)
    uyap_runs.save_audit_run(other, w.bob, REQUEST)
    w.become(w.alice)
    export = account_export.build_export(w.connection, w.alice, office.EXPORT_ONLY_TABLES)
    assert [r["id"] for r in export["office"]["uyap_audit_runs"]] == [own.id]
    w.become(None)
    w.connection.execute("SELECT set_config('app.user_id', '', true)")
    counts = account.purge_user_data(w.connection, w.alice)
    assert counts["office_uyap_audit_runs"] == 1
    assert w.connection.execute("SELECT id FROM office_uyap_audit_runs WHERE owner_id=%s", (w.alice,)).fetchall() == []
    assert w.connection.execute("SELECT id FROM office_uyap_audit_runs WHERE owner_id=%s", (w.bob,)).fetchone()["id"] == other.id
