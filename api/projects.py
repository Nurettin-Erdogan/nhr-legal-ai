from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.audit import PROJECT_CREATE, AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])

MatterType = Literal["case", "enforcement", "consultancy", "research", "other"]
ProjectStatus = Literal["active", "on_hold", "closed", "archived"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    matter_type: MatterType = "case"
    reference_no: str | None = Field(default=None, max_length=100)
    court_name: str | None = Field(default=None, max_length=250)
    chamber: str | None = Field(default=None, max_length=200)
    docket_no: str | None = Field(default=None, max_length=100)
    opened_on: date | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    matter_type: MatterType
    status: ProjectStatus
    reference_no: str | None
    court_name: str | None
    chamber: str | None
    docket_no: str | None
    opened_on: date | None
    member_role: str
    document_count: int
    created_at: datetime
    updated_at: datetime


_PROJECT_SELECT = """
SELECT
    project.id,
    project.name,
    project.description,
    project.matter_type,
    project.status,
    project.reference_no,
    project.court_name,
    project.chamber,
    project.docket_no,
    project.opened_on,
    member.member_role,
    (
        SELECT count(*) FROM documents
        WHERE documents.project_id = project.id AND documents.deleted_at IS NULL
    ) AS document_count,
    project.created_at,
    project.updated_at
FROM projects project
JOIN project_members member
  ON member.project_id = project.id AND member.user_id = app_current_user_id()
WHERE project.deleted_at IS NULL
"""


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    user_id: Annotated[UUID, Depends(current_user_id)],
) -> list[ProjectResponse]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            rows = connection.execute(
                _PROJECT_SELECT + " ORDER BY project.updated_at DESC"
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("Projeler alınamadı")
        raise HTTPException(status_code=503, detail="Projeler alınamadı") from exc
    return [ProjectResponse(**row) for row in rows]


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    request: ProjectCreate,
    user_id: Annotated[UUID, Depends(current_user_id)],
    http_request: Request,
) -> ProjectResponse:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            # The id is generated here instead of read back with RETURNING: the
            # select policy is applied to the returned row and cannot yet see a
            # project the current statement is inserting.
            project_id = uuid4()
            connection.execute(
                """
                INSERT INTO projects (
                    id, name, description, created_by, matter_type, reference_no,
                    court_name, chamber, docket_no, opened_on
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    project_id,
                    request.name.strip(),
                    request.description.strip() if request.description else None,
                    user_id,
                    request.matter_type,
                    request.reference_no,
                    request.court_name,
                    request.chamber,
                    request.docket_no,
                    request.opened_on,
                ),
            )
            connection.execute(
                """
                INSERT INTO project_members (project_id, user_id, member_role, added_by)
                VALUES (%s, %s, 'owner', %s)
                """,
                (project_id, user_id, user_id),
            )
            record_event(
                connection,
                action=PROJECT_CREATE,
                actor_user_id=user_id,
                context=AuditContext.from_request(http_request),
                entity_type="project",
                entity_id=project_id,
                project_id=project_id,
                metadata={"matter_type": request.matter_type},
            )
            row = connection.execute(
                _PROJECT_SELECT + " AND project.id = %s", (project_id,)
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("Proje oluşturulamadı")
        raise HTTPException(status_code=503, detail="Proje oluşturulamadı") from exc
    return ProjectResponse(**row)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
) -> ProjectResponse:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            row = connection.execute(
                _PROJECT_SELECT + " AND project.id = %s", (project_id,)
            ).fetchone()
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail="Proje alınamadı") from exc
    if not row:
        raise HTTPException(status_code=404, detail="Proje bulunamadı")
    return ProjectResponse(**row)
