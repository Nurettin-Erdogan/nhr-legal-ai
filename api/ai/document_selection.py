"""Açık belge seçimini RLS altında doğrular; hazır olmayan alt kümeyle sessizce ilerlemez."""
from uuid import UUID

import psycopg
from fastapi import HTTPException

from api.db import authenticated_database_connection
from api.ai.workspace_scope import require_project_documents


def selected_document_coverage(owner: UUID | None, ids: list[UUID], case_id: UUID | None = None, office_project_id: UUID | None = None) -> dict:
    if owner is None:
        raise HTTPException(401, "Seçili belgelerle çalışmak için oturum açmalısınız")
    if office_project_id:
        require_project_documents(owner, office_project_id, ids)
    try:
        with authenticated_database_connection(str(owner)) as connection:
            rows = connection.execute(
                "SELECT od.id, (d.metadata->>'ocr')='true' AS ocr, "
                "(d.status='ready' AND EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id=d.id)) AS ready "
                "FROM office_case_documents od LEFT JOIN documents d "
                "ON d.office_case_document_id=od.id AND d.deleted_at IS NULL "
                "WHERE od.id=ANY(%s::uuid[]) AND od.deleted_at IS NULL "
                "AND (%s::uuid IS NULL OR od.case_id=%s)", (ids, case_id, case_id),
            ).fetchall()
    except psycopg.Error as exc:
        raise HTTPException(503, "Belge erişimi doğrulanamadı") from exc
    if {row['id'] for row in rows} != set(ids):
        raise HTTPException(404, "Seçili belgeler bulunamadı veya erişim yetkiniz yok. Listeyi yenileyin.")
    if not all(row['ready'] for row in rows):
        raise HTTPException(409, "Seçili belgelerin tamamının metni henüz okunabilir değil. Belge listesini yenileyin.")
    return {"total": len(rows), "ready": len(rows), "pending": 0,
            "ocr": sum(bool(row['ocr']) for row in rows), "failed": []}
