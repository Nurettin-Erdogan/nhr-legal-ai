"""Büro projesinin belge bağlantıları: dosya taşımadan/kopyalamadan, owner RLS altında."""
from typing import Annotated
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from api.ai.workspace_scope import office_project_case, project_document_coverage, project_document_predicate, PROJECT_INDEX_STATUS, PROJECT_INDEX_ERROR
from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection
from api.document_indexing import schedule_index

router = APIRouter(prefix='/api/office/projects', tags=['project-documents'])


class LinkDocuments(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=2000)


@router.get('/{project_id}/documents')
def list_project_documents(project_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 500, offset: Annotated[int, Query(ge=0, le=100000)] = 0) -> dict:
    case_id = office_project_case(user_id, project_id)
    try:
        coverage = project_document_coverage(user_id, project_id)
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                "SELECT od.id,od.file_name,od.size_bytes,od.source,od.doc_type,od.doc_date,od.case_id,od.created_at,"
                "od.uyap_file_no,od.uyap_birim,"+PROJECT_INDEX_STATUS+" AS status,"+PROJECT_INDEX_ERROR+" AS error,"
                "COALESCE((d.metadata->>'ocr')='true',false) AS ocr, "
                "EXISTS(SELECT 1 FROM office_project_documents link WHERE link.project_id=%(office_project_id)s "
                "AND link.document_id=od.id) AS direct_linked "
                "FROM office_case_documents od LEFT JOIN documents d ON d.office_case_document_id=od.id AND d.deleted_at IS NULL "
                "WHERE od.deleted_at IS NULL AND " + project_document_predicate() +
                " ORDER BY od.created_at DESC,od.id DESC LIMIT %(limit)s OFFSET %(offset)s",
                {'office_project_id':project_id,'limit':limit,'offset':offset},
            ).fetchall()
    except psycopg.Error as exc:
        raise HTTPException(503, 'Proje belgeleri alınamadı.') from exc
    return {'project_id':project_id,'case_id':case_id,**coverage,'documents':rows,'offset':offset,'limit':limit}


@router.post('/{project_id}/documents')
def link_project_documents(project_id: UUID, body: LinkDocuments, user_id: Annotated[UUID, Depends(current_user_id)], request: Request) -> dict:
    office_project_case(user_id, project_id)
    ids = list(dict.fromkeys(body.document_ids))
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            # Kaynak silme/çöpe taşıma, doğrulama ile INSERT arasına giremez.
            rows = connection.execute(
                'SELECT od.id,d.id IS NULL AS needs_index FROM office_case_documents od '
                'LEFT JOIN documents d ON d.office_case_document_id=od.id '
                'WHERE od.id=ANY(%s::uuid[]) AND od.deleted_at IS NULL FOR SHARE OF od', (ids,),
            ).fetchall()
            if {row['id'] for row in rows} != set(ids):
                raise HTTPException(404, 'Seçili belgeler bulunamadı veya erişim yetkiniz yok.')
            count = connection.execute(
                'INSERT INTO office_project_documents(id,owner_id,project_id,document_id) '
                'SELECT item.id,%s,%s,item.document_id FROM unnest(%s::uuid[],%s::uuid[]) AS item(id,document_id) '
                'ON CONFLICT(project_id,document_id) DO NOTHING', (user_id,project_id,[uuid4() for _ in ids],ids),
            ).rowcount
            record_event(connection, action='office.project_documents.link', actor_user_id=user_id,
                context=AuditContext.from_request(request), entity_type='office_projects', entity_id=project_id,
                metadata={'linked':count,'already_linked':len(ids)-count})
    except psycopg.errors.ForeignKeyViolation as exc:
        raise HTTPException(409, 'Proje veya belge değişti. Listeyi yenileyin.') from exc
    except psycopg.Error as exc:
        raise HTTPException(503, 'Belgeler projeye bağlanamadı.') from exc
    for row in rows:
        if row['needs_index']:
            schedule_index(user_id,row['id'],audit=AuditContext.from_request(request))
    return {'linked':count,'already_linked':len(ids)-count}


@router.delete('/{project_id}/documents/{document_id}', status_code=204)
def unlink_project_document(project_id: UUID, document_id: UUID, user_id: Annotated[UUID, Depends(current_user_id)], request: Request) -> Response:
    office_project_case(user_id, project_id)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            count = connection.execute('DELETE FROM office_project_documents WHERE project_id=%s AND document_id=%s',
                (project_id,document_id)).rowcount
            if count:
                record_event(connection, action='office.project_documents.unlink', actor_user_id=user_id,
                    context=AuditContext.from_request(request), entity_type='office_projects', entity_id=project_id,
                    metadata={'unlinked':count})
    except psycopg.Error as exc:
        raise HTTPException(503, 'Belge bağlantısı kaldırılamadı.') from exc
    return Response(status_code=204)
