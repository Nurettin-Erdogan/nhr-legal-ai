"""Owner-scoped, evidence-linked office suggestions. No model/portal calls.

Reading never creates tasks/events. Each explicit decision is revalidated and
committed with its action under a per-owner/key transaction lock.
"""
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

router = APIRouter(prefix="/api/bureau-assistant", tags=["bureau-assistant"])
ZONE = ZoneInfo("Europe/Istanbul")


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
        if row["status"] == "closed" or when < now:
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
        key = f"document:{row['id']}"
        if key in handled:
            continue
        result.append(dict(key=key, kind="document", title=f"Belgeyi incele: {row['file_name']}"[:200],
            description="Henüz işlem yapılmamış belge için inceleme görevi önerisi. Belgenin içeriği yorumlanmadı ve tebligat/süre sonucu çıkarılmadı.",
            case_id=str(row["case_id"]) if row["case_id"] else None,
            case_title=row.get("case_title") or "Davaya bağlı değil", source_label=row["file_name"],
            source_url=f"/dashboard/cases/{row['case_id']}" if row["case_id"] else "/dashboard/files",
            date=row["created_at"].isoformat(), priority="medium", action_label="Görev oluştur"))
    return sorted(result, key=lambda r: (r["priority"] != "high", r["kind"] != "hearing", r["date"]))


def snapshot(db, now):
    now = now.astimezone(ZONE)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    hearings = db.execute("""SELECT id,title,case_no,court,status,next_hearing FROM office_cases
        WHERE status <> 'closed' AND next_hearing >= %s
        ORDER BY next_hearing,id""", (now,)).fetchall()
    documents = db.execute("""SELECT d.id,d.case_id,d.file_name,d.created_at,c.title AS case_title
        FROM office_case_documents d LEFT JOIN office_cases c ON c.id=d.case_id
        WHERE d.deleted_at IS NULL
        ORDER BY d.created_at DESC,d.id""").fetchall()
    keys = [f"hearing:{r['id']}:{r['next_hearing'].isoformat()}" for r in hearings]
    keys += [f"document:{r['id']}" for r in documents]
    decisions = db.execute("SELECT proposal_key FROM office_bureau_decisions WHERE proposal_key=ANY(%s)", (keys,)).fetchall()
    calendar = db.execute("""SELECT case_id,start_at FROM office_calendar_events
        WHERE event_type='hearing' AND start_at >= %s""",
        (now,)).fetchall()
    tasks = db.execute("""SELECT id,title,status,due_date,case_id FROM office_tasks
        WHERE status <> 'done' ORDER BY due_date NULLS LAST,id""").fetchall()
    counts = db.execute("""SELECT count(*) FILTER (WHERE status <> 'done') AS open_tasks,
        count(*) FILTER (WHERE status <> 'done' AND due_date < %s) AS overdue_tasks,
        count(*) FILTER (WHERE status <> 'done' AND due_date >= %s AND due_date < %s) AS today_tasks
        FROM office_tasks""", (now, day_start, day_end)).fetchone()
    counts["today_hearings"] = db.execute("""SELECT count(*) AS count FROM office_cases
        WHERE status <> 'closed' AND next_hearing >= %s AND next_hearing < %s""",
        (day_start, day_end)).fetchone()["count"]
    counts["upcoming_hearings"] = db.execute("""SELECT count(*) AS count FROM office_cases
        WHERE status <> 'closed' AND next_hearing >= %s""",
        (now,)).fetchone()["count"]
    return dict(proposals=proposals(hearings, documents, decisions, calendar, now),
        hearings=hearings, tasks=tasks, counts=counts,
        limited=False,
        generated_at=now.isoformat(), window_days=None)


@router.get("")
def overview(owner: Annotated[UUID, Depends(current_user_id)]):
    try:
        with authenticated_database_connection(str(owner)) as db:
            return snapshot(db, datetime.now(ZONE))
    except psycopg.Error as error:
        raise HTTPException(503, "Büro özeti alınamadı. Veriler boş kabul edilmedi; lütfen yeniden deneyin.") from error


def _review_content(db, proposal, now):
    document_id = UUID(proposal["key"].split(":", 2)[1]) if proposal["kind"] == "document" else None
    rows = db.execute("""SELECT od.id, od.file_name, d.status,
        COALESCE((d.metadata->>'ocr') = 'true', false) AS ocr,
        (SELECT left(c.content,1800) FROM document_chunks c
         WHERE c.document_id=d.id ORDER BY c.chunk_index,c.id LIMIT 1) AS excerpt
        FROM office_case_documents od
        LEFT JOIN documents d ON d.office_case_document_id=od.id
        WHERE od.deleted_at IS NULL AND
        ((%s::uuid IS NOT NULL AND od.id=%s) OR
         (%s::uuid IS NULL AND od.case_id=%s::uuid))
        ORDER BY od.created_at DESC,od.id""",
        (document_id, document_id, document_id, proposal["case_id"])).fetchall()
    documents = [dict(id=str(r["id"]), file_name=r["file_name"],
                      ready=r["status"] == "ready" and bool(r["excerpt"]),
                      ocr=bool(r["ocr"]),
                      excerpt=r["excerpt"] if r["status"] == "ready" else None)
                 for r in rows]
    return dict(proposal=proposal, documents=documents, limited=False,
                suggested_action=proposal["description"], generated_at=now.isoformat(),
                action_available=True)


def review(db, key, now):
    """Read-only evidence preview; source identities come from the owner's live proposals."""
    proposal = next((p for p in snapshot(db, now)["proposals"] if p["key"] == key), None)
    if proposal is None:
        raise HTTPException(409, "Öneri değişmiş veya artık geçerli değil. Listeyi yenileyin.")
    return _review_content(db, proposal, now)


def preparation(db, case_id, now):
    """Saved case context, not a legal assessment; remains readable after calendar approval."""
    case = db.execute("""SELECT id,title,case_no,court,status,next_hearing FROM office_cases
        WHERE id=%s""", (case_id,)).fetchone()
    if case is None:
        raise HTTPException(404, "Dava bulunamadı veya erişim yetkiniz yok.")
    if case["next_hearing"] is None:
        raise HTTPException(409, "Bu davanın kayıtlı duruşma tarihi yok.")
    when = case["next_hearing"]
    key = f"hearing:{case['id']}:{when.isoformat()}"
    proposal = dict(key=key, kind="hearing", title=f"Duruşma: {case['title']}"[:200],
                    description="Kayıtlı duruşma tarihini kontrol ederek takvime ekleyin.",
                    case_id=str(case["id"]), case_title=case["title"],
                    source_label=case["case_no"] or case["court"] or "Dava kaydı",
                    source_url=f"/dashboard/cases/{case['id']}", date=when.isoformat(),
                    priority="high" if when - now < timedelta(days=2) else "medium",
                    action_label="Takvime ekle")
    result = _review_content(db, proposal, now)
    counts = db.execute("""SELECT count(*) AS total,
        count(*) FILTER (WHERE EXISTS (SELECT 1 FROM documents d
          WHERE d.office_case_document_id=od.id AND d.status='ready'
          AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id=d.id))) AS ready
        FROM office_case_documents od WHERE case_id=%s AND deleted_at IS NULL""", (case_id,)).fetchone()
    tasks = db.execute("""SELECT id,title,status,due_date FROM office_tasks
        WHERE case_id=%s AND status <> 'done' ORDER BY due_date NULLS LAST,id""", (case_id,)).fetchall()
    handled = db.execute("SELECT status FROM office_bureau_decisions WHERE proposal_key=%s", (key,)).fetchone()
    scheduled = db.execute("""SELECT id FROM office_calendar_events
        WHERE case_id=%s AND event_type='hearing' AND start_at=%s LIMIT 1""", (case_id, when)).fetchone()
    result["action_available"] = (case["status"] != "closed" and now <= when
                                  and not handled and not scheduled)
    result["preparation"] = dict(
        case_no=case["case_no"], court=case["court"], status=case["status"], hearing_at=when.isoformat(),
        total_documents=counts["total"], ready_documents=counts["ready"],
        tasks=[dict(id=str(t["id"]), title=t["title"], status=t["status"],
                    due_date=t["due_date"].isoformat() if t["due_date"] else None) for t in tasks],
        tasks_limited=False,
        checklist=["Kayıtlı duruşma tarihini ve mahkemeyi asıl dosyadan kontrol edin.",
                   "Belge özetini kaynak metinlerle karşılaştırın; okunamayan belgeleri ayrıca inceleyin.",
                   "Açık görevlerin tamamlanma durumunu kontrol edin; bu liste hukuki yükümlülük tespiti değildir."],
    )
    return result


@router.get("/cases/{case_id}/preparation")
def case_preparation(case_id: UUID, response: Response,
                     owner: Annotated[UUID, Depends(current_user_id)]):
    response.headers["Cache-Control"] = "no-store"
    try:
        with authenticated_database_connection(str(owner)) as db:
            return preparation(db, case_id, datetime.now(ZONE))
    except psycopg.Error as error:
        raise HTTPException(503, "Duruşma hazırlık bilgileri alınamadı. Yeniden deneyin.") from error


@router.get("/review")
def review_proposal(response: Response, owner: Annotated[UUID, Depends(current_user_id)],
                    key: Annotated[str, Query(min_length=1, max_length=240)]):
    response.headers["Cache-Control"] = "no-store"
    try:
        with authenticated_database_connection(str(owner)) as db:
            return review(db, key, datetime.now(ZONE))
    except psycopg.Error as error:
        raise HTTPException(503, "Kaynak belgeler alınamadı. Yeniden deneyin.") from error


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
