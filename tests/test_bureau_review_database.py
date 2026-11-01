"""Bureau review against the disposable RLS database, never production."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from api import bureau_assistant as bureau
from tests.test_case_document_rag import _case, _indexed_document, db, needs_db  # noqa: F401


@needs_db
def test_review_reads_only_current_owners_selected_document_and_denies_other_owner(db):  # noqa: F811 - imported pytest fixture
    case = _case(db, db.alice)
    document = _indexed_document(db, db.alice, case, "Sentetik belge metni. Dosya incelemesi gereklidir.")
    other = _indexed_document(db, db.alice, case, "Başka belge metni.")
    now = datetime.now(bureau.ZONE)
    key = f"document:{document}"
    db.become(db.alice)
    review = bureau.review(db.connection, key, now)
    assert [d["id"] for d in review["documents"]] == [str(document)]
    assert review["documents"][0]["ready"]
    assert "Sentetik belge" in review["documents"][0]["excerpt"]
    assert str(other) not in str(review)
    db.become(db.bob)
    with pytest.raises(HTTPException) as exc:
        bureau.review(db.connection, key, now)
    assert exc.value.status_code == 409
    db.become(None)
    db.connection.execute("UPDATE office_case_documents SET deleted_at=now() WHERE id=%s", (document,))
    db.become(db.alice)
    with pytest.raises(HTTPException):
        bureau.review(db.connection, key, now)


@needs_db
def test_hearing_review_documents_stay_in_the_selected_case(db):  # noqa: F811 - imported pytest fixture
    case, other = _case(db, db.alice), _case(db, db.alice)
    included = _indexed_document(db, db.alice, case, "Seçili dosyanın belge metni.")
    excluded = _indexed_document(db, db.alice, other, "Diğer dosyanın belge metni.")
    now = datetime.now(bureau.ZONE)
    when = now + timedelta(days=1)
    db.become(None)
    db.connection.execute("UPDATE office_cases SET next_hearing=%s WHERE id=%s", (when, case))
    db.become(db.alice)
    proposal = next(p for p in bureau.snapshot(db.connection, now)["proposals"] if p["kind"] == "hearing")
    review = bureau.review(db.connection, proposal["key"], now)
    assert [d["id"] for d in review["documents"]] == [str(included)]
    assert str(excluded) not in str(review)


@needs_db
def test_preparation_is_owner_scoped_and_remains_available_after_calendar_approval(db):  # noqa: F811 - imported pytest fixture
    from uuid import uuid4

    case, other = _case(db, db.alice), _case(db, db.alice)
    included = _indexed_document(db, db.alice, case, "Dosyada kayıtlı sentetik belge.")
    now = datetime.now(bureau.ZONE)
    when = now + timedelta(days=1)
    db.become(None)
    db.connection.execute("UPDATE office_cases SET next_hearing=%s WHERE id=%s", (when, case))
    for task_case, title, status in [(case, "İncelenecek kayıt", "todo"),
                                      (case, "Bitmiş iş", "done"), (other, "Başka dava işi", "todo")]:
        db.connection.execute("INSERT INTO office_tasks(id,owner_id,case_id,title,status) VALUES (%s,%s,%s,%s,%s)",
                              (uuid4(), db.alice, task_case, title, status))
    db.become(db.alice)
    result = bureau.preparation(db.connection, case, now)
    assert result["action_available"] is True
    assert result["preparation"]["total_documents"] == 1
    assert result["preparation"]["ready_documents"] == 1
    assert [t["title"] for t in result["preparation"]["tasks"]] == ["İncelenecek kayıt"]
    assert result["documents"][0]["id"] == str(included)
    db.connection.execute("""INSERT INTO office_calendar_events(id,owner_id,case_id,title,event_type,start_at)
        VALUES (%s,%s,%s,'Duruşma','hearing',%s)""", (uuid4(), db.alice, case, when))
    result = bureau.preparation(db.connection, case, now)
    assert result["action_available"] is False
    assert result["preparation"]["tasks"]
    db.become(db.bob)
    with pytest.raises(HTTPException) as exc:
        bureau.preparation(db.connection, case, now)
    assert exc.value.status_code == 404
