"""Büro projesini çekirdek RAG projesiyle karıştırmadan, RLS altında davaya çözer."""
from uuid import UUID

import psycopg
from fastapi import HTTPException

from api.db import authenticated_database_connection

PROJECT_INDEX_STATUS = "CASE WHEN d.status='ready' AND NOT EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id=d.id) THEN 'failed' ELSE COALESCE(d.status,'pending') END"
PROJECT_INDEX_ERROR = "CASE WHEN d.status='ready' AND NOT EXISTS (SELECT 1 FROM document_chunks c WHERE c.document_id=d.id) THEN 'Belgenin metin parçaları bulunamadı; yeniden işleyin.' ELSE d.processing_error END"


def project_document_predicate(alias: str = 'od') -> str:
    """Yalnız sabit kod alias'ları; kimlik değerleri her zaman bağlı parametre."""
    if alias not in ('od', 'office_doc'):
        raise ValueError('Geçersiz SQL alias')
    return (
        "EXISTS (SELECT 1 FROM office_projects p WHERE p.id=%(office_project_id)s "
        f"AND ({alias}.case_id=p.case_id OR EXISTS (SELECT 1 FROM office_project_documents link "
        f"WHERE link.project_id=p.id AND link.document_id={alias}.id)))"
    )


def project_document_coverage(owner: UUID, project_id: UUID) -> dict:
    with authenticated_database_connection(str(owner)) as connection:
        rows = connection.execute(
            "SELECT od.file_name,"+PROJECT_INDEX_STATUS+" AS status,"+PROJECT_INDEX_ERROR+" AS processing_error,(d.metadata->>'ocr')='true' AS ocr "
            "FROM office_case_documents od LEFT JOIN documents d ON d.office_case_document_id=od.id AND d.deleted_at IS NULL "
            "WHERE od.deleted_at IS NULL AND " + project_document_predicate(), {'office_project_id': project_id},
        ).fetchall()
    return {'total':len(rows), 'ready':sum(row['status']=='ready' for row in rows),
            'pending':sum(row['status'] not in ('ready','failed') for row in rows),
            'ocr':sum(row['status']=='ready' and bool(row['ocr']) for row in rows),
            'failed':[{'file_name':row['file_name'],'reason':row['processing_error'] or 'Belge işlenemedi.'} for row in rows if row['status']=='failed']}


def require_project_documents(owner: UUID, project_id: UUID, ids: list[UUID]) -> None:
    office_project_case(owner, project_id)
    try:
        with authenticated_database_connection(str(owner)) as connection:
            rows = connection.execute(
                "SELECT od.id FROM office_case_documents od WHERE od.id=ANY(%(ids)s::uuid[]) "
                "AND od.deleted_at IS NULL AND " + project_document_predicate(), {'ids':ids,'office_project_id':project_id},
            ).fetchall()
    except psycopg.Error as exc:
        raise HTTPException(503, 'Proje belge kapsamı doğrulanamadı.') from exc
    if {row['id'] for row in rows} != set(ids):
        raise HTTPException(409, 'Belge artık bu projenin kapsamında değil. Proje belgelerini yenileyin.')


def office_project_case(owner: UUID | None, project_id: UUID) -> UUID | None:
    if owner is None:
        raise HTTPException(401, "Proje sohbeti için oturum açmalısınız")
    try:
        with authenticated_database_connection(str(owner)) as connection:
            row = connection.execute(
                "SELECT p.case_id FROM office_projects p LEFT JOIN office_cases c ON c.id=p.case_id "
                "WHERE p.id=%s AND (p.case_id IS NULL OR c.id IS NOT NULL)", (project_id,),
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(503, "Proje erişimi doğrulanamadı") from exc
    if row is None:
        raise HTTPException(404, "Proje bulunamadı veya erişim yetkiniz yok")
    return row['case_id']
