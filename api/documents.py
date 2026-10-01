from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from api.audit import DOCUMENT_UPLOAD, AuditContext, record_event
from api.auth.routes import current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection
from api.document_processing import (
    DocumentProcessingError,
    process_document,
    safe_file_name,
    store_document_file,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    id: UUID
    project_id: UUID | None
    file_name: str
    mime_type: str | None
    file_size: int | None
    status: str
    processing_error: str | None
    chunk_count: int
    created_at: datetime
    processed_at: datetime | None


_DOCUMENT_SELECT = """
SELECT
    document.id,
    document.project_id,
    document.file_name,
    document.mime_type,
    document.file_size,
    document.status,
    document.processing_error,
    (
        SELECT count(*) FROM document_chunks AS chunk
        WHERE chunk.document_id = document.id
    ) AS chunk_count,
    document.created_at,
    document.processed_at
FROM documents AS document
WHERE document.deleted_at IS NULL
"""


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    user_id: Annotated[UUID, Depends(current_user_id)],
    project_id: UUID | None = None,
) -> list[DocumentResponse]:
    query = _DOCUMENT_SELECT
    params: tuple[UUID, ...] = ()
    if project_id is not None:
        query += " AND document.project_id = %s"
        params = (project_id,)
    query += " ORDER BY document.created_at DESC"
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(query, params).fetchall()
    except psycopg.Error as exc:
        logger.exception("Belgeler alınamadı")
        raise HTTPException(status_code=503, detail="Belgeler alınamadı") from exc
    return [DocumentResponse(**row) for row in rows]


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user_id: Annotated[UUID, Depends(current_user_id)],
    file: Annotated[UploadFile, File()],
    http_request: Request,
    project_id: Annotated[UUID | None, Form()] = None,
) -> DocumentResponse:
    settings = get_settings()
    file_name = safe_file_name(file.filename)
    data = await file.read(settings.max_document_size_bytes + 1)
    await file.close()
    if len(data) > settings.max_document_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Belge en fazla {settings.max_document_size_bytes // 1024 // 1024} MB olabilir.",
        )

    try:
        processed = process_document(file_name, data)
    except DocumentProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document_id = uuid4()
    storage_path: Path | None = None
    try:
        storage_key, storage_path = store_document_file(
            settings.document_storage_dir,
            str(user_id),
            str(document_id),
            processed.extension,
            data,
        )
        with authenticated_database_connection(str(user_id)) as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    id, project_id, uploaded_by, file_name, mime_type, storage_key,
                    storage_bucket, status, file_size, checksum_sha256, metadata,
                    processed_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, 'local', 'ready', %s, %s, %s, NOW()
                )
                """,
                (
                    document_id,
                    project_id,
                    user_id,
                    file_name,
                    processed.mime_type,
                    storage_key,
                    len(data),
                    processed.checksum_sha256,
                    Jsonb({"original_content_type": file.content_type}),
                ),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO document_chunks (
                        id, document_id, chunk_index, content, page_number,
                        section_title, content_hash, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                    """,
                    [
                        (
                            uuid4(),
                            document_id,
                            chunk.index,
                            chunk.content,
                            chunk.page_number,
                            chunk.section_title,
                            chunk.content_hash,
                        )
                        for chunk in processed.chunks
                    ],
                )
            # Dosya adı ve içerik günlüğe yazılmaz; yalnız belge kimliği ve boyut/parça özeti.
            record_event(
                connection,
                action=DOCUMENT_UPLOAD,
                actor_user_id=user_id,
                context=AuditContext.from_request(http_request),
                entity_type="document",
                entity_id=document_id,
                project_id=project_id,
                metadata={
                    "extension": processed.extension,
                    "file_size": len(data),
                    "chunk_count": len(processed.chunks),
                },
            )
            row = connection.execute(
                _DOCUMENT_SELECT + " AND document.id = %s", (document_id,)
            ).fetchone()
    except psycopg.errors.InsufficientPrivilege as exc:
        if storage_path:
            storage_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=403, detail="Bu projeye belge ekleme yetkiniz yok."
        ) from exc
    except psycopg.errors.ForeignKeyViolation as exc:
        if storage_path:
            storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="Proje bulunamadı.") from exc
    except (psycopg.Error, OSError) as exc:
        if storage_path:
            storage_path.unlink(missing_ok=True)
        logger.exception("Belge yüklenemedi")
        raise HTTPException(status_code=503, detail="Belge yüklenemedi") from exc

    if row is None:
        if storage_path:
            storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Belge kaydı doğrulanamadı")
    return DocumentResponse(**row)
