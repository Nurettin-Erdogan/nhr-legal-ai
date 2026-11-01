"""UYAP sayfa yapısı tanı kayıtları: içerik/kimlik benzeri metin reddi, sahibe özel, sınırlı (gerçek RLS'li veritabanında)."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from api import uyap_diagnostics
from api.uyap_diagnostics import Diagnostic, save_diagnostic
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)

REQUEST = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
REPORT = {"extensionVersion": "2.26.43", "frame": "üst", "path": "/main/jsp/xxxxxx/xxxxx.jsp", "tables": 3,
          "tree": {"folders": 4, "files": 12}, "docUrlShapes": [{"shape": "/main/jsp/x.uyap?param", "count": 3}]}


@pytest.mark.parametrize("leak", ["12345678901", "05321234567", "ayse@example.com", "x" * 201])
def test_text_that_looks_like_content_or_identity_is_refused(leak):
    with pytest.raises(ValueError):
        uyap_diagnostics._clean({"field": leak})


def test_a_structure_only_report_passes_the_filter():
    assert uyap_diagnostics._clean([REPORT]) == [REPORT]


@pytest.fixture
def world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(uyap_diagnostics, "authenticated_database_connection", as_user)
    monkeypatch.setattr(uyap_diagnostics.AuditContext, "from_request", staticmethod(lambda request: None))
    return db


@needs_db
def test_a_report_is_saved_for_its_owner_only_and_audited_without_content(world):
    out = save_diagnostic(Diagnostic(code="no_list", context={"phase": "liste"}, reports=[REPORT]), world.alice, REQUEST)
    assert out["saved"] is True
    world.become(world.alice)
    [row] = world.connection.execute("SELECT code, context, reports FROM office_uyap_diagnostics").fetchall()
    assert row["code"] == "no_list" and row["reports"] == [REPORT]
    world.become(world.bob)
    assert world.connection.execute("SELECT count(*) AS n FROM office_uyap_diagnostics").fetchone()["n"] == 0
    world.become(None)
    [event] = world.connection.execute(
        "SELECT metadata FROM activity_logs WHERE action = 'office.uyap_diagnostic' AND actor_user_id = %s", (world.alice,)
    ).fetchall()
    assert event["metadata"] == {"code": "no_list", "reports": 1}


@needs_db
def test_a_report_carrying_an_id_number_is_refused_and_nothing_is_stored(world):
    with pytest.raises(HTTPException) as refused:
        save_diagnostic(Diagnostic(code="no_tree", reports=[{**REPORT, "title": "10000000146"}]), world.alice, REQUEST)
    assert refused.value.status_code == 422
    world.become(world.alice)
    assert world.connection.execute("SELECT count(*) AS n FROM office_uyap_diagnostics").fetchone()["n"] == 0


@needs_db
def test_reports_are_rate_limited_and_capped_per_owner(world, monkeypatch):
    monkeypatch.setattr(uyap_diagnostics, "MAX_PER_HOUR", 3)
    results = [save_diagnostic(Diagnostic(code="no_list", reports=[REPORT]), world.alice, REQUEST)["saved"] for _ in range(5)]
    assert results == [True, True, True, False, False]
    monkeypatch.setattr(uyap_diagnostics, "MAX_PER_HOUR", 100)
    monkeypatch.setattr(uyap_diagnostics, "MAX_PER_OWNER", 4)
    for _ in range(3):
        save_diagnostic(Diagnostic(code="no_list", reports=[REPORT]), world.alice, REQUEST)
    world.become(world.alice)
    assert world.connection.execute("SELECT count(*) AS n FROM office_uyap_diagnostics").fetchone()["n"] == 4
