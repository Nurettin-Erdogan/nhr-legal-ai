"""Dava belgeleri çöp kutusu uçları (bkz. api/document_trash.py ve docs/office-document-trash.md)."""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from api.audit import AuditContext
from api.auth.routes import current_user_id
from api.document_trash import (
    RETENTION_DAYS,
    delete_forever,
    list_trash,
    restore_document,
    trash_document,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/office/documents", tags=["office-trash"])

_NOT_FOUND = "Belge bulunamadı veya erişim yetkiniz yok"


def _unavailable(exc: psycopg.Error) -> HTTPException:
    logger.exception("Çöp kutusu işlemi başarısız")
    return HTTPException(status_code=503, detail="Çöp kutusu işlemi şu anda yapılamıyor")


@router.get("/trash")
def trash_list(
    user_id: Annotated[UUID, Depends(current_user_id)], case_id: UUID | None = None
) -> dict[str, Any]:
    """Çöpteki belgeler; her biri için kalan gün ve ona dayanan sohbet cevabı sayısı."""
    try:
        documents = list_trash(user_id, case_id)
    except psycopg.Error as exc:
        raise _unavailable(exc) from exc
    return {"retention_days": RETENTION_DAYS, "documents": documents}


@router.post("/{document_id}/trash")
def trash(
    document_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)], request: Request
) -> dict[str, Any]:
    try:
        moved = trash_document(user_id, document_id, AuditContext.from_request(request))
    except psycopg.Error as exc:
        raise _unavailable(exc) from exc
    if not moved:
        # Başkasının belgesi, olmayan belge ve zaten çöpteki belge ayırt edilmez.
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {"id": document_id, "trashed": True, "retention_days": RETENTION_DAYS}


@router.post("/{document_id}/restore")
def restore(
    document_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)], request: Request
) -> dict[str, Any]:
    try:
        restored = restore_document(user_id, document_id, AuditContext.from_request(request))
    except psycopg.Error as exc:
        raise _unavailable(exc) from exc
    if not restored:
        raise HTTPException(status_code=404, detail="Belge çöp kutusunda bulunamadı")
    return {"id": document_id, "trashed": False}


@router.delete("/{document_id}")
def delete_permanently(
    document_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)], request: Request
) -> dict[str, Any]:
    """Belgeyi KALICI siler. Yalnız çöpteki belge silinebilir; geri alınamaz."""
    try:
        outcome = delete_forever(user_id, document_id, AuditContext.from_request(request))
    except psycopg.Error as exc:
        raise _unavailable(exc) from exc
    if outcome.status == "not_found":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if outcome.status == "not_trashed":
        raise HTTPException(status_code=409, detail="Belge önce çöp kutusuna taşınmalı; kalıcı silme yalnız çöpteki belge için yapılır")
    return {"id": document_id, "deleted": True, "redacted_answers": outcome.redacted_answers}
