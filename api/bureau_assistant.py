"""Owner-scoped, evidence-linked office suggestions. No model/portal calls.

Reading never creates tasks/events. Each explicit decision is revalidated and
committed with its action under a per-owner/key transaction lock.
"""
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

router = APIRouter(prefix="/api/bureau-assistant", tags=["bureau-assistant"])
ZONE = ZoneInfo("Europe/Istanbul")
LIMIT = 100


class Decision(BaseModel):
    key: str = Field(min_length=1, max_length=240)
    action: Literal["approve", "dismiss"]
    title: str | None = Field(default=None, min_length=1, max_length=200)


def proposals(hearings, documents, decisions, calendar, now):
    """No inferred legal deadlines: only saved hearing dates and document arrivals."""
    handled = {r["proposal_key"] for r in decisions}
    scheduled = {(str(r["case_id"]), r["start_at"]) for r in calendar}
    result = []
    for row in hearings:
        when = row["next_hearing"]
        if row["status"] == "closed" or not now <= when <= now + timedelta(days=7):
            continue
        key = f"hearing:{row['id']}:{when.isoformat()}"
        if key in handled or (str(row["id"]), when) in scheduled:
            continue
        result.append(dict(key=key, kind="hearing", title=f"Duruşma: {row['title']}"[:200],
            description="Davaya kayıtlı duruşma tarihini takvime ekleyin. Tarih dosya kaydından alınmıştır; yeni bir hukuki süre hesaplanmadı.",
            case_id=str(row["id"]), case_title=row["title"], source_label=row.get("case_no") or row.get("court") or "Dava kaydı",
            source_url=f"/dashboard/cases/{row['id']}", date=when.isoformat(),
            priority="high" if when - now < timedelta(days=2) else "medium", action_label="Takvime ekle"))
    for row in documents:
        if row["created_at"] < now - timedelta(days=7):
            continue
        key = f"document:{row['id']}"
        if key in handled:
            continue
        result.append(dict(key=key, kind="document", title=f"Belgeyi incele: {row['file_name']}"[:200],
            description="Son 7 günde eklenen belge için inceleme görevi önerisi. Belgenin içeriği yorumlanmadı ve tebligat/süre sonucu çıkarılmadı.",
            case_id=str(row["case_id"]) if row["case_id"] else None,
            case_title=row.get("case_title") or "Davaya bağlı değil", source_label=row["file_name"],
            source_url=f"/dashboard/cases/{row['case_id']}" if row["case_id"] else "/dashboard/files",
            date=row["created_at"].isoformat(), priority="medium", action_label="Görev oluştur"))
    return sorted(result, key=lambda r: (r["priority"] != "high", r["kind"] != "hearing", r["date"]))


def snapshot(db, now):
    hearings = db.execute("""SELECT id,title,case_no,court,status,next_hearing FROM office_cases
        WHERE status <> 'closed' AND next_hearing >= %s AND next_hearing <= %s
        ORDER BY next_hearing,id LIMIT 101""", (now, now + timedelta(days=7))).fetchall()
    documents = db.execute("""SELECT d.id,d.case_id,d.file_name,d.created_at,c.title AS case_title
        FROM office_case_documents d LEFT JOIN office_cases c ON c.id=d.case_id
        WHERE d.deleted_at IS NULL AND d.created_at >= %s
        ORDER BY d.created_at DESC,d.id LIMIT 101""", (now - timedelta(days=7),)).fetchall()
    keys = [f"hearing:{r['id']}:{r['next_hearing'].isoformat()}" for r in hearings[:LIMIT]]
    keys += [f"document:{r['id']}" for r in documents[:LIMIT]]
    decisions = db.execute("SELECT proposal_key FROM office_bureau_decisions WHERE proposal_key=ANY(%s)", (keys,)).fetchall()
    calendar = db.execute("""SELECT case_id,start_at FROM office_calendar_events
        WHERE event_type='hearing' AND start_at >= %s AND start_at <= %s""",
        (now, now + timedelta(days=7))).fetchall()
    tasks = db.execute("""SELECT id,title,status,due_date,case_id FROM office_tasks
        WHERE status <> 'done' ORDER BY due_date NULLS LAST,id LIMIT 8""").fetchall()
    counts = db.execute("""SELECT count(*) FILTER (WHERE status <> 'done') AS open_tasks,
        count(*) FILTER (WHERE status <> 'done' AND due_date < %s) AS overdue_tasks
        FROM office_tasks""", (now,)).fetchone()
    counts["upcoming_hearings"] = db.execute("""SELECT count(*) AS count FROM office_cases
        WHERE status <> 'closed' AND next_hearing >= %s AND next_hearing <= %s""",
        (now, now + timedelta(days=7))).fetchone()["count"]
    return dict(proposals=proposals(hearings[:LIMIT], documents[:LIMIT], decisions, calendar, now),
        hearings=hearings[:8], tasks=tasks, counts=counts,
        limited=len(hearings) > LIMIT or len(documents) > LIMIT,
        generated_at=now.isoformat(), window_days=7)


@router.get("")
def overview(owner: Annotated[UUID, Depends(current_user_id)]):
    try:
        with authenticated_database_connection(str(owner)) as db:
            return snapshot(db, datetime.now(ZONE))
    except psycopg.Error as error:
        raise HTTPException(503, "Büro özeti alınamadı. Veriler boş kabul edilmedi; lütfen yeniden deneyin.") from error


def decide(db, owner, body, audit, now):
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"bureau:{owner}:{body.key}",))
    previous = db.execute("""SELECT status,task_id,event_id FROM office_bureau_decisions
        WHERE proposal_key=%s""", (body.key,)).fetchone()
    if previous:
        return dict(previous, repeated=True)
    # Only typed server-generated keys; lock the source before deriving actions.
    parts = body.key.split(":", 2)
    try:
        source = UUID(parts[1]) if parts[0] in {"hearing", "document"} else None
    except (ValueError, IndexError):
        source = None
    if source is None:
        raise HTTPException(404, "Öneri bulunamadı")
    if parts[0] == "hearing":
        db.execute("SELECT id FROM office_cases WHERE id=%s FOR SHARE", (source,)).fetchone()
    else:
        db.execute("SELECT id FROM office_case_documents WHERE id=%s AND deleted_at IS NULL FOR SHARE", (source,)).fetchone()
    proposal = next((p for p in snapshot(db, now)["proposals"] if p["key"] == body.key), None)
    if proposal is None:
        raise HTTPException(409, "Kaynak değişmiş veya öneri artık geçerli değil. Listeyi yenileyin.")
    title = (body.title or proposal["title"]).strip()
    if not title:
        raise HTTPException(422, "Başlık boş olamaz")
    task_id = event_id = None
    if body.action == "approve":
        target = uuid5(NAMESPACE_URL, f"bureau:{owner}:{body.key}")
        if proposal["kind"] == "hearing":
            event_id = target
            db.execute("""INSERT INTO office_calendar_events
                (id,owner_id,case_id,title,description,event_type,start_at,reminder_minutes)
                VALUES (%s,%s,%s,%s,%s,'hearing',%s,1440) ON CONFLICT(id) DO NOTHING""",
                (target,owner,proposal["case_id"],title,proposal["description"],proposal["date"]))
        else:
            task_id = target
            db.execute("""INSERT INTO office_tasks(id,owner_id,case_id,title,description,priority,status)
                VALUES (%s,%s,%s,%s,%s,'medium','todo') ON CONFLICT(id) DO NOTHING""",
                (target,owner,proposal["case_id"],title,proposal["description"]))
    status = "approved" if body.action == "approve" else "dismissed"
    db.execute("""INSERT INTO office_bureau_decisions(id,owner_id,proposal_key,status,task_id,event_id)
        VALUES (%s,%s,%s,%s,%s,%s)""", (uuid4(),owner,body.key,status,task_id,event_id))
    record_event(db, action=f"bureau.{status}", actor_user_id=owner, entity_type="bureau_suggestion",
        entity_id=source, context=audit, metadata={"kind":proposal["kind"]}, strict=True)
    return dict(status=status, task_id=task_id, event_id=event_id, repeated=False)


@router.post("/decisions")
def decision(body: Decision, request: Request, owner: Annotated[UUID, Depends(current_user_id)]):
    try:
        with authenticated_database_connection(str(owner)) as db:
            return decide(db, owner, body, AuditContext.from_request(request), datetime.now(ZONE))
    except psycopg.Error as error:
        raise HTTPException(503, "İşlem kaydedilemedi. Listeyi yenileyerek sonucu kontrol edin; tekrar deneme aynı kaydı çoğaltmaz.") from error
