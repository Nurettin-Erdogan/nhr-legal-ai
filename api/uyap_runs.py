"""Owner-scoped UYAP run checkpoints, including empty, failed and unprocessed files.

Only bounded report metadata is stored, never tokens, document bodies or detail tables.
These are dated observations, not a claim that today's portal still has the same state.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.uyap_cases import case_number, court_key
from api.uyap_sync import _find_case, _server_documents

logger = logging.getLogger(__name__)


def _private_history_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/office/uyap", tags=["office"], dependencies=[Depends(_private_history_response)])


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunDetail(ReportModel):
    state: Literal["complete", "partial", "failed", "skipped"]
    tabs: int = Field(ge=0, le=20)
    saved: bool
    problems: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=6)


class RunTiming(ReportModel):
    """Dosyada harcanan saniyeler (hız ölçümü); evrak içeriği taşımaz."""

    tree: float = Field(ge=0, le=86_400)
    pull: float = Field(ge=0, le=86_400)
    detail: float = Field(ge=0, le=86_400)


class RunFile(ReportModel):
    esas: str = Field(max_length=60)
    birim: str = Field(max_length=160)
    yargiTuru: str = Field(default="", max_length=80)
    outcome: Literal["complete", "empty", "incomplete", "failed", "pending"]
    declared: int = Field(ge=0, le=1_000_000)
    found: int = Field(ge=0, le=1_000_000)
    stored: int = Field(ge=0, le=1_000_000)
    sent: int = Field(ge=0, le=1_000_000)
    missing: int = Field(ge=0, le=1_000_000)
    pulls: int = Field(ge=0, le=100)
    problems: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=6)
    detail: RunDetail | None = None
    timing: RunTiming | None = None
    # UYAP'ın "sisteme yüklenmemiş" dediği evraklar: found/missing'e girmez (içerik UYAP'ta yok).
    absent: int = Field(default=0, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.stored + self.missing != self.found:
            raise ValueError("Kayıtlı ve eksik evrak toplamı bulunan evrak sayısıyla uyuşmalı")
        if self.outcome == "complete" and (not self.found or self.missing):
            raise ValueError("Eksiksiz dosyada evrak bulunmalı ve eksik olmamalı")
        if self.outcome in {"empty", "pending"} and (self.found or self.sent or self.declared):
            raise ValueError("Evraksız/işlenmemiş dosyada evrak sayısı bildirilemez")
        return self


class RunSaveNote(ReportModel):
    kind: Literal["ok", "warn"]
    text: str = Field(max_length=1000)


class RunCheckpoint(ReportModel):
    id: UUID
    revision: int = Field(ge=1, le=1_000_000)
    finished: bool
    verify_only: bool
    list_complete: bool
    aborted: bool = False
    stopped_because: str | None = Field(default=None, max_length=1000)
    save_note: RunSaveNote | None = None
    reports: list[RunFile] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def unique_files(self):
        identities = [(case_number(r.esas), court_key(r.birim), r.yargiTuru) for r in self.reports]
        if len(set(identities)) != len(identities):
            raise ValueError("Koşuda aynı dosya birden çok kez bulunamaz")
        return self


def _verified_snapshot(connection, owner: UUID, body: RunCheckpoint) -> dict[str, Any]:
    snapshot = body.model_dump(mode="json", exclude={"id", "revision"})
    for report in snapshot["reports"]:
        number, court = case_number(report["esas"]), court_key(report["birim"])
        case_id, _ = _find_case(connection, owner, number, court) if number and court else (None, "no_case")
        if report["outcome"] == "complete":
            stored = _server_documents(connection, owner, case_id) if case_id else 0
            if stored < report["found"]:
                report["outcome"] = "incomplete"
                report["stored"] = min(report["stored"], stored)
                report["missing"] = report["found"] - report["stored"]
                report["problems"] = ["Sunucu evrak eksiksizliğini doğrulamadı.", *report["problems"]][:6]
        detail = report.get("detail")
        if detail and detail["saved"]:
            stored_detail = connection.execute(
                "SELECT complete FROM office_uyap_case_detail WHERE owner_id=%s AND case_id=%s",
                (owner, case_id),
            ).fetchone() if case_id else None
            if not stored_detail or (detail["state"] == "complete" and not stored_detail["complete"]):
                detail["saved"] = bool(stored_detail)
                detail["state"] = "partial" if stored_detail else "failed"
                detail["problems"] = ["Sunucu dosya bilgilerinin kaydını doğrulamadı.", *detail["problems"]][:6]
    return snapshot


@router.post("/audit-runs")
def save_audit_run(body: RunCheckpoint, user_id: Annotated[UUID, Depends(current_user_id)], request: Request):
    if len(body.model_dump_json().encode("utf-8")) > 2_000_000:
        raise HTTPException(status_code=413, detail="UYAP raporu boyut sınırını aşıyor")
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            # Serialize concurrent revisions, including the first INSERT. Never overwrite a final run with an old checkpoint.
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(body.id),))
            old = connection.execute(
                "SELECT revision, finished FROM office_uyap_audit_runs WHERE id=%s AND owner_id=%s",
                (body.id, user_id),
            ).fetchone()
            if old and (body.revision <= old["revision"] or old["finished"]):
                raise HTTPException(status_code=409, detail="Koşunun daha yeni veya tamamlanmış kaydı var")
            snapshot = _verified_snapshot(connection, user_id, body)
            if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > 2_000_000:
                raise HTTPException(status_code=413, detail="UYAP raporu boyut sınırını aşıyor")
            if old:
                connection.execute(
                    "UPDATE office_uyap_audit_runs SET revision=%s, finished=%s, snapshot=%s, updated_at=clock_timestamp() "
                    "WHERE id=%s AND owner_id=%s",
                    (body.revision, body.finished, Jsonb(snapshot), body.id, user_id),
                )
            else:
                connection.execute(
                    "INSERT INTO office_uyap_audit_runs (id,owner_id,revision,finished,snapshot) VALUES (%s,%s,%s,%s,%s)",
                    (body.id, user_id, body.revision, body.finished, Jsonb(snapshot)),
                )
            if body.finished:
                record_event(connection, action="office.uyap_audit_run", actor_user_id=user_id,
                             context=AuditContext.from_request(request), entity_type="uyap_run", entity_id=body.id,
                             metadata={"files": len(body.reports), "verify_only": body.verify_only})
    except psycopg.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Koşu kimliği kullanılamıyor") from exc
    except psycopg.Error as exc:
        logger.exception("UYAP tam koşu raporu kaydedilemedi")
        raise HTTPException(status_code=503, detail="Tam koşu raporu kaydedilemedi") from exc
    return {"id": body.id, "revision": body.revision, "snapshot": snapshot}


@router.get("/audit-runs")
def load_audit_runs(user_id: Annotated[UUID, Depends(current_user_id)]):
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                "SELECT id,revision,finished,snapshot,created_at,updated_at FROM office_uyap_audit_runs "
                "WHERE owner_id=%s ORDER BY created_at DESC,id DESC LIMIT 5", (user_id,),
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("UYAP tam koşu raporu okunamadı")
        raise HTTPException(status_code=503, detail="Tam koşu raporu okunamadı") from exc
    return {"runs": rows}
