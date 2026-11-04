"""Kalıcı, kullanıcıya özel belge kuyruğu; metnin tamamı pencere pencere işlenir."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import suppress
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api import case_summary
from api.draft_documents import DraftFields
from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.ai.workspace_scope import project_document_predicate, require_project_documents

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/office-ai/jobs", tags=["document-jobs"])
MAX_DOCUMENTS = 2000
_tasks: dict[tuple[UUID, UUID], asyncio.Task] = {}


class JobRequest(BaseModel):
    draft_fields: DraftFields = Field(default_factory=DraftFields)
    module: Literal["document_analysis", "auto_summary", "risk_analysis", "draft"]
    document_ids: list[UUID] = Field(default_factory=list, max_length=MAX_DOCUMENTS)
    text: str = Field(default="", max_length=2_000_000)
    prompt: str = Field(default="Seçili belgeleri incele.", max_length=20000)
    title: str = Field(default="Belge çalışması", max_length=200)
    case_id: UUID | None = None
    project_id: UUID | None = None
    doc_type: Literal["dilekce", "sozlesme", "ihtarname", "diger"] = "dilekce"
    parties: list[str] = Field(default_factory=list, max_length=20)
    subject: str = Field(default="", max_length=2000)
    details: str = Field(default="", max_length=8000)


def _public(row: dict) -> dict:
    result = {
        key: row[key]
        for key in (
            "id",
            "module",
            "state",
            "output_id",
            "error",
            "created_at",
            "updated_at",
        )
    }
    # Yoklamada bütün türetilmiş metni tekrar taşımayız; çıktı yalnız tek iş detayında verilir.
    result["progress"] = {key: row["progress"].get(key, 0) for key in ("total", "done")}
    result["progress"]["documents"] = [
        {
            key: document.get(key)
            for key in ("file_name", "windows_done", "windows_total", "errors")
        }
        for document in row["progress"].get("documents", [])
    ]
    return result


def _read(owner: UUID, job_id: UUID) -> dict:
    with authenticated_database_connection(str(owner)) as connection:
        row = connection.execute(
            "SELECT * FROM office_document_jobs WHERE id=%s", (job_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Belge işi bulunamadı veya erişim yetkiniz yok.")
        result = _public(row)
        if row["output_id"]:
            output = connection.execute(
                "SELECT output FROM office_ai_outputs WHERE id=%s", (row["output_id"],)
            ).fetchone()
            result["output"] = output["output"] if output else None
        return result


def _create(owner: UUID, body: JobRequest, audit: AuditContext) -> UUID:
    ids = list(dict.fromkeys(body.document_ids))
    if not ids and not body.text.strip():
        raise HTTPException(422, "Belge seçin veya işlenecek metni ekleyin.")
    if ids and body.text.strip():
        raise HTTPException(
            422, "Kayıtlı belgelerle yapıştırılmış metni aynı işte kullanmayın."
        )
    if body.project_id and ids:
        require_project_documents(owner, body.project_id, ids)
    job_id = uuid4()
    with authenticated_database_connection(str(owner)) as connection:
        # Aynı sahibin eşzamanlı başlatmaları sıralanır; başka kullanıcı etkilenmez.
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"document-jobs:{owner}",),
        )
        if connection.execute(
            "SELECT id FROM office_document_jobs WHERE state IN ('queued','running') LIMIT 1"
        ).fetchone():
            raise HTTPException(
                409,
                "Devam eden belge işiniz var. Tamamlanmasını bekleyin veya durdurun.",
            )
        if (
            body.case_id
            and not connection.execute(
                "SELECT id FROM office_cases WHERE id=%s", (body.case_id,)
            ).fetchone()
        ):
            raise HTTPException(404, "Dava bulunamadı veya erişim yetkiniz yok.")
        if (
            body.project_id
            and not connection.execute(
                "SELECT id FROM office_projects WHERE id=%s", (body.project_id,)
            ).fetchone()
        ):
            raise HTTPException(404, "Proje bulunamadı veya erişim yetkiniz yok.")
        if ids:
            rows = connection.execute(
                "SELECT od.id FROM office_case_documents od WHERE od.id=ANY(%s::uuid[]) AND od.deleted_at IS NULL "
                "AND (%s::uuid IS NULL OR od.case_id=%s) AND EXISTS (SELECT 1 FROM documents d "
                "WHERE d.office_case_document_id=od.id AND d.status='ready' AND d.deleted_at IS NULL "
                "AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id=d.id))",
                (ids, body.case_id, body.case_id),
            ).fetchall()
            if {row["id"] for row in rows} != set(ids):
                raise HTTPException(
                    409,
                    "Seçili belgelerin tamamı erişilebilir ve metni okunmuş olmalı. Belge listesini yenileyin.",
                )
        connection.execute(
            "INSERT INTO office_document_jobs (id,owner_id,module,document_ids,payload,progress) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                job_id,
                owner,
                body.module,
                ids,
                Jsonb(body.model_dump(mode="json")),
                Jsonb({"total": len(ids) or 1, "done": 0, "documents": []}),
            ),
        )
        record_event(
            connection,
            action="office.document_job.start",
            actor_user_id=owner,
            context=audit,
            entity_type="office_document_jobs",
            entity_id=job_id,
            metadata={"documents": len(ids) or 1},
        )
    return job_id


def _claim(owner: UUID, job_id: UUID, lease: UUID) -> dict | None:
    with authenticated_database_connection(str(owner)) as connection:
        return connection.execute(
            "UPDATE office_document_jobs SET state='running',lease=%s,leased_until=now()+interval '90 seconds' "
            "WHERE id=%s AND (state='queued' OR (state='running' AND leased_until<now())) RETURNING *",
            (lease, job_id),
        ).fetchone()


def _touch(
    owner: UUID, job_id: UUID, lease: UUID, progress: dict | None = None
) -> bool:
    with authenticated_database_connection(str(owner)) as connection:
        return (
            connection.execute(
                "UPDATE office_document_jobs SET leased_until=now()+interval '90 seconds', updated_at=clock_timestamp(), "
                "progress=COALESCE(%s::jsonb,progress) WHERE id=%s AND lease=%s AND state='running' RETURNING id",
                (Jsonb(progress) if progress is not None else None, job_id, lease),
            ).fetchone()
            is not None
        )


def _document(owner: UUID, document_id: UUID) -> dict:
    with authenticated_database_connection(str(owner)) as connection:
        row = connection.execute(
            "SELECT od.id,od.file_name,(d.metadata->>'ocr')='true' AS ocr, "
            "(SELECT string_agg(c.content,E'\\n\\n' ORDER BY c.chunk_index) FROM document_chunks c WHERE c.document_id=d.id) AS text "
            "FROM office_case_documents od JOIN documents d ON d.office_case_document_id=od.id "
            "WHERE od.id=%s AND od.deleted_at IS NULL AND d.deleted_at IS NULL AND d.status='ready'",
            (document_id,),
        ).fetchone()
        if row is None or not (row["text"] or "").strip():
            raise HTTPException(
                409, "Belge artık okunabilir değil veya erişimden kaldırıldı."
            )
        return row


def full_windows(text: str, *, risk: bool = False) -> list[str]:
    # Üstteki limit belge uzunluğundan büyüktür; son pencereler asla atılmaz.
    from api.deep_research import MAX_QUESTION_CHARS

    return case_summary.split_windows(
        text,
        size=MAX_QUESTION_CHARS - 400 if risk else case_summary.WINDOW_CHARS,
        limit=max(1, len(text)),
    )[0]


async def process_window(
    module: str, window: str, name: str, doc_id: UUID, owner: UUID, prompt: str
) -> dict:
    from api import office_ai

    if module == "risk_analysis":
        result = await office_ai._risk(
            f"{prompt[:150]}\nBelge: {name[:80]}\n{window}", owner
        )
        return {
            "answer": result["content"],
            "sources": result["sources"],
            "bullets": [],
            # A completed research loop is not necessarily a fully verified
            # report. Preserve section failures so the queue becomes partial.
            "errors": result.get("errors", []),
        }

    async def generate(system: str, text: str) -> str:
        return (await office_ai._generate(system, text))[0]

    if module == "document_analysis":
        summary = await case_summary.analyze_document_window(
            doc_id, name, window, instruction=prompt, generate=generate
        )
    else:
        summary = await case_summary.summarize_document(
            doc_id, name, window, ocr=False, generate=generate, max_windows=1
        )
    errors = [summary.error] if summary.error else []
    if summary.dropped:
        errors.append(
            f"{summary.dropped} model maddesi kaynak belgeyle doğrulanamadığı için gösterilmedi."
        )
    return {
        "answer": "",
        "sources": [],
        "bullets": summary.bullets,
        "errors": errors,
        "facts": case_summary.extract_facts(window),
    }


def render_progress(progress: dict) -> str:
    lines = [
        "# Belge bazlı çalışma",
        "",
        "_Kullanıcı belgelerinden üretilmiştir. Okuma kapsamı ve doğrulanamayan bölümler aşağıda gösterilir._",
        "",
    ]
    for document in progress.get("documents", []):
        lines += [
            f"## {document['file_name']}",
            f"Okunan bölüm: {document.get('windows_done', 0)}/{document.get('windows_total', 0)}",
            "",
        ]
        if document.get("ocr"):
            lines.append("_Metin OCR ile çıkarılmıştır; asıl belgeyle kontrol edin._")
        lines += [f"- {bullet}" for bullet in document.get("bullets", [])]
        facts = document.get("facts", {})
        for key, label in (
            ("dates", "Metindeki tarihler"),
            ("amounts", "Metindeki tutarlar"),
            ("esas", "Metindeki esas numaraları"),
            ("karar", "Metindeki karar numaraları"),
        ):
            if facts.get(key):
                lines.append(f"**{label}:** {', '.join(facts[key])}")
        for section in document.get("sections", []):
            lines += [f"### Bölüm {section['index']}", section["answer"], ""]
        lines += [
            f"_Tamamlanamayan bölüm: {error}_" for error in document.get("errors", [])
        ]
        lines.append("")
    return "\n".join(lines)


def _finish(
    owner: UUID,
    job_id: UUID,
    lease: UUID,
    progress: dict,
    output: str,
    state: str,
    payload: dict,
    legal_sources: list | None = None,
) -> bool:
    output_id = uuid4()
    with authenticated_database_connection(str(owner)) as connection:
        job = connection.execute(
            "SELECT id,document_ids,output_id FROM office_document_jobs WHERE id=%s AND lease=%s AND state='running' FOR UPDATE",
            (job_id, lease),
        ).fetchone()
        if job is None:
            return False
        if job["document_ids"]:
            if payload.get("project_id"):
                available = connection.execute(
                    "SELECT od.id FROM office_case_documents od WHERE od.id=ANY(%(ids)s::uuid[]) "
                    "AND od.deleted_at IS NULL AND " + project_document_predicate(),
                    {
                        "ids": job["document_ids"],
                        "office_project_id": payload["project_id"],
                    },
                ).fetchall()
            else:
                available = connection.execute(
                    "SELECT id FROM office_case_documents WHERE id=ANY(%s) AND deleted_at IS NULL",
                    (job["document_ids"],),
                ).fetchall()
            if len(available) != len(job["document_ids"]):
                state = "partial"
                output = "_Bazı kaynak belgeler işlem sırasında erişimden kaldırıldı; çıktı kaydedilmedi._"
                progress = {
                    "total": progress["total"],
                    "done": progress["done"],
                    "documents": [],
                }
                legal_sources = []
        sources = [
            {
                "verification": "user_document"
                if job["document_ids"]
                else "user_input",
                "document_id": document["id"] if job["document_ids"] else None,
                "job_id": str(job_id),
                "file_name": document["file_name"],
                "windows_done": document.get("windows_done", 0),
                "windows_total": document.get("windows_total", 0),
            }
            for document in progress.get("documents", [])
        ]
        for document in progress.get("documents", []):
            for section in document.get("sections", []):
                sources.extend(section.get("sources", []))
        sources.extend(legal_sources or [])
        connection.execute(
            "INSERT INTO office_ai_outputs (id,owner_id,module,title,prompt,output,sources,case_id,project_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                output_id,
                owner,
                payload["module"],
                payload["title"],
                payload["prompt"],
                output,
                Jsonb(sources),
                payload.get("case_id"),
                payload.get("project_id"),
            ),
        )
        connection.execute(
            "UPDATE office_document_jobs SET state=%s,output_id=%s,progress=%s,lease=NULL,leased_until=NULL,updated_at=clock_timestamp() WHERE id=%s AND lease=%s",
            (state, output_id, Jsonb(progress), job_id, lease),
        )
        # Yeniden denemede eski kısmi çıktı ve türetilmiş metin yetim kalmaz.
        # İş önce yeni çıktıya bağlanır; çıktı silme triggerı yeni işi kaldırmaz.
        if job.get("output_id"):
            connection.execute(
                "DELETE FROM office_ai_outputs WHERE id=%s", (job["output_id"],)
            )
        record_event(
            connection,
            action="office.document_job.finish",
            actor_user_id=owner,
            entity_type="office_document_jobs",
            entity_id=job_id,
            metadata={"documents": progress["done"], "complete": state == "done"},
        )
    return True


async def _worker(owner: UUID, job_id: UUID) -> None:
    lease = uuid4()
    try:
        row = await asyncio.to_thread(_claim, owner, job_id, lease)
    except Exception:
        logger.warning("Belge işi alınamadı job=%s", job_id)
        return
    if row is None:
        return
    progress = row["progress"]
    payload = row["payload"]
    alive = True

    async def heartbeat():
        nonlocal alive
        while alive:
            await asyncio.sleep(20)
            try:
                alive = await asyncio.to_thread(_touch, owner, job_id, lease)
            except Exception:
                alive = False

    pulse = asyncio.create_task(heartbeat())
    try:
        ids = row["document_ids"] or [None]
        for index, document_id in enumerate(ids):
            if not alive:
                return
            if index < progress.get("done", 0):
                continue
            try:
                if document_id and payload.get("project_id"):
                    await asyncio.to_thread(
                        require_project_documents,
                        owner,
                        UUID(payload["project_id"]),
                        [document_id],
                    )
                document = (
                    await asyncio.to_thread(_document, owner, document_id)
                    if document_id
                    else {
                        "id": job_id,
                        "file_name": payload["title"],
                        "text": payload["text"],
                        "ocr": False,
                    }
                )
                windows = full_windows(
                    document["text"], risk=payload["module"] == "risk_analysis"
                )
                digest = hashlib.sha256(document["text"].encode()).hexdigest()
                existing = next(
                    (
                        item
                        for item in progress["documents"]
                        if item["id"] == str(document["id"])
                    ),
                    None,
                )
                if existing and existing.get("hash") != digest:
                    progress["documents"].remove(existing)
                    existing = None
                current = existing or {
                    "id": str(document["id"]),
                    "file_name": document["file_name"],
                    "ocr": bool(document["ocr"]),
                    "hash": digest,
                    "windows_total": len(windows),
                    "windows_done": 0,
                    "bullets": [],
                    "sections": [],
                    "errors": [],
                    "facts": {},
                }
                if existing is None:
                    progress["documents"].append(current)
                for window_index, window in enumerate(windows):
                    if window_index < current["windows_done"]:
                        continue
                    if not await asyncio.to_thread(
                        _touch, owner, job_id, lease, progress
                    ):
                        return
                    try:
                        part = await process_window(
                            payload["module"],
                            window,
                            document["file_name"],
                            document["id"],
                            owner,
                            payload["prompt"],
                        )
                        current["bullets"] = list(
                            dict.fromkeys([*current["bullets"], *part["bullets"]])
                        )
                        current["errors"].extend(
                            f"{window_index + 1}: {error}" for error in part["errors"]
                        )
                        for key, values in part.get("facts", {}).items():
                            if isinstance(values, list):
                                current.setdefault("facts", {}).setdefault(key, [])
                                current["facts"][key] = list(
                                    dict.fromkeys([*current["facts"][key], *values])
                                )
                        if part["answer"]:
                            current["sections"].append(
                                {
                                    "index": window_index + 1,
                                    "answer": part["answer"],
                                    "sources": part["sources"],
                                }
                            )
                    except Exception:
                        logger.warning(
                            "Belge işi bölüm hatası job=%s document=%s",
                            job_id,
                            document["id"],
                        )
                        current["errors"].append(
                            f"{window_index + 1}: Bu bölüm tamamlanamadı."
                        )
                    current["windows_done"] = window_index + 1
                    if not await asyncio.to_thread(
                        _touch, owner, job_id, lease, progress
                    ):
                        return
            except HTTPException as exc:
                progress["documents"] = [
                    item
                    for item in progress["documents"]
                    if item["id"] != str(document_id)
                ]
                progress["documents"].append(
                    {
                        "id": str(document_id),
                        "file_name": "Erişilemeyen belge",
                        "errors": [str(exc.detail)],
                        "windows_total": 0,
                        "windows_done": 0,
                    }
                )
            progress["done"] = index + 1
            if not await asyncio.to_thread(_touch, owner, job_id, lease, progress):
                return
        output = render_progress(progress)
        legal_sources = []
        if payload["module"] == "draft":
            output, legal_sources = await draft_from_progress(owner, payload, progress)
        state = (
            "partial"
            if any(item.get("errors") for item in progress["documents"])
            else "done"
        )
        await asyncio.to_thread(
            _finish,
            owner,
            job_id,
            lease,
            progress,
            output,
            state,
            payload,
            legal_sources,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Belge işi durdu job=%s", job_id)
        with suppress(Exception):
            await asyncio.to_thread(_fail, owner, job_id, lease)
    finally:
        alive = False
        pulse.cancel()
        with suppress(asyncio.CancelledError):
            await pulse


async def draft_from_progress(
    owner: UUID, payload: dict, progress: dict
) -> tuple[str, list]:
    """Doğrulanmış tüm pencere olgularını ana taslağa koyar; yeniden kısaltıp bilgi atmaz."""
    from api import office_ai, draft_documents

    subject = payload["subject"] or payload["prompt"][:200]
    contexts = await office_ai._retrieve_sources(subject, owner, top_k=12)
    suggested = await asyncio.to_thread(office_ai._statute_hints, subject)
    legal = draft_documents.legal_references(
        contexts, question=subject, suggested=suggested
    )
    paragraphs = []
    given_facts = draft_documents.facts_source(subject, payload.get("details"))
    if given_facts:
        paragraphs.append("Kullanıcının verdiği açıklamalar: " + given_facts)
    for document in progress["documents"]:
        paragraphs.extend(
            f"{document['file_name']} belgesinden: {bullet}"
            for bullet in document.get("bullets", [])
        )
    content = draft_documents.build_document(
        payload["doc_type"],
        payload["title"],
        payload["parties"],
        subject,
        paragraphs,
        legal,
        payload.get("draft_fields"),
    )
    content += "\n\n## Belge okuma kapsamı\n"
    for document in progress["documents"]:
        content += f"\n- {document['file_name']}: {document.get('windows_done', 0)}/{document.get('windows_total', 0)} bölüm."
        if document.get("ocr"):
            content += " OCR metni; aslıyla kontrol edin."
        for error in document.get("errors", []):
            content += f"\n  - Tamamlanamayan bölüm: {error}"
    return content, legal.sources


def _fail(owner: UUID, job_id: UUID, lease: UUID):
    with authenticated_database_connection(str(owner)) as connection:
        connection.execute(
            "UPDATE office_document_jobs SET state='failed',error='İş tamamlanamadı; kaydedilen ilerleme korunuyor.',lease=NULL,leased_until=NULL WHERE id=%s AND lease=%s",
            (job_id, lease),
        )


def ensure_worker(owner: UUID, job_id: UUID):
    key = (owner, job_id)
    if key not in _tasks or _tasks[key].done():
        task = asyncio.create_task(_worker(owner, job_id))
        _tasks[key] = task
        task.add_done_callback(
            lambda finished: _tasks.pop(key, None)
            if _tasks.get(key) is finished
            else None
        )


@router.post("", status_code=202)
async def start_job(
    body: JobRequest, request: Request, owner: Annotated[UUID, Depends(current_user_id)]
):
    try:
        job_id = await asyncio.to_thread(
            _create, owner, body, AuditContext.from_request(request)
        )
    except psycopg.Error as exc:
        raise HTTPException(
            503, "Belge kuyruğu kullanılamıyor. Veritabanı migrationını kontrol edin."
        ) from exc
    ensure_worker(owner, job_id)
    return {"job_id": job_id}


@router.get("")
async def list_jobs(owner: Annotated[UUID, Depends(current_user_id)]):
    rows = await asyncio.to_thread(_list, owner)
    for row in rows:
        if row["state"] in ("queued", "running"):
            ensure_worker(owner, row["id"])
    return {"jobs": [_public(row) for row in rows]}


def _list(owner: UUID) -> list[dict]:
    with authenticated_database_connection(str(owner)) as connection:
        return connection.execute(
            "SELECT * FROM office_document_jobs ORDER BY created_at DESC LIMIT 20"
        ).fetchall()


@router.get("/{job_id}")
async def get_job(job_id: UUID, owner: Annotated[UUID, Depends(current_user_id)]):
    result = await asyncio.to_thread(_read, owner, job_id)
    if result["state"] in ("queued", "running"):
        ensure_worker(owner, job_id)
    return result


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: UUID, request: Request, owner: Annotated[UUID, Depends(current_user_id)]
):
    with authenticated_database_connection(str(owner)) as connection:
        row = connection.execute(
            "UPDATE office_document_jobs SET state='cancelled',lease=NULL,leased_until=NULL,updated_at=clock_timestamp() WHERE id=%s AND state IN ('queued','running') RETURNING id",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Devam eden iş bulunamadı.")
        record_event(
            connection,
            action="office.document_job.cancel",
            actor_user_id=owner,
            context=AuditContext.from_request(request),
            entity_type="office_document_jobs",
            entity_id=job_id,
        )
    return {"cancelled": True}


def _resume(owner: UUID, job_id: UUID, audit: AuditContext) -> None:
    with authenticated_database_connection(str(owner)) as connection:
        connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"document-jobs:{owner}",),
        )
        row = connection.execute(
            "SELECT * FROM office_document_jobs WHERE id=%s FOR UPDATE", (job_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Belge işi bulunamadı.")
        if row["state"] not in ("failed", "partial", "cancelled"):
            raise HTTPException(409, "Bu iş yeniden başlatılamaz.")
        if connection.execute(
            "SELECT id FROM office_document_jobs WHERE state IN ('queued','running') LIMIT 1"
        ).fetchone():
            raise HTTPException(
                409, "Önce devam eden belge işini tamamlayın veya durdurun."
            )
        progress = row["progress"]
        progress["done"] = 0
        for document in progress.get("documents", []):
            if document.get("errors"):
                document.update(
                    windows_done=0, errors=[], bullets=[], sections=[], facts={}
                )
        connection.execute(
            "UPDATE office_document_jobs SET state='queued',error=NULL,lease=NULL,leased_until=NULL,progress=%s,updated_at=clock_timestamp() WHERE id=%s",
            (Jsonb(progress), job_id),
        )
        record_event(
            connection,
            action="office.document_job.resume",
            actor_user_id=owner,
            context=audit,
            entity_type="office_document_jobs",
            entity_id=job_id,
        )


@router.post("/{job_id}/resume", status_code=202)
async def resume_job(
    job_id: UUID, request: Request, owner: Annotated[UUID, Depends(current_user_id)]
):
    await asyncio.to_thread(_resume, owner, job_id, AuditContext.from_request(request))
    ensure_worker(owner, job_id)
    return {"job_id": job_id}
