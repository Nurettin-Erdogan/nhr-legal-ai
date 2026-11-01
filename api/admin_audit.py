"""Denetim günlüğünü okuma (yalnız yönetici).

Sorgular `authenticated_database_connection` ile çalışır: `activity_logs` SELECT politikası
yöneticiye tüm kayıtları, diğer kullanıcılara yalnız kendi kayıtlarını gösterir. Uç nokta ek olarak
`require_admin` ile korunur; yazma ucu yoktur (kayıtlar yalnız uygulama içinden eklenir).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.admin_ingestion import require_admin
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/audit", tags=["admin-audit"])


class AuditEntry(BaseModel):
    id: UUID
    created_at: datetime
    actor_user_id: UUID | None
    action: str
    entity_type: str | None
    entity_id: UUID | None
    project_id: UUID | None
    request_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)


_LIST_SQL = """
SELECT
    id, created_at, actor_user_id, action, entity_type, entity_id, project_id,
    request_id, host(ip_address) AS ip_address, user_agent, metadata
FROM activity_logs
WHERE (%(action)s::text IS NULL OR action = %(action)s)
  AND (%(actor)s::uuid IS NULL OR actor_user_id = %(actor)s)
  AND (%(project)s::uuid IS NULL OR project_id = %(project)s)
  AND (%(before)s::timestamptz IS NULL OR created_at < %(before)s)
ORDER BY created_at DESC, id DESC
LIMIT %(limit)s
"""


@router.get("", response_model=list[AuditEntry])
def list_audit_entries(
    admin_id: Annotated[UUID, Depends(require_admin)],
    action: Annotated[str | None, Query(max_length=64)] = None,
    actor_user_id: UUID | None = None,
    project_id: UUID | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEntry]:
    parameters = {
        "action": action,
        "actor": actor_user_id,
        "project": project_id,
        "before": before,
        "limit": limit,
    }
    try:
        with authenticated_database_connection(str(admin_id)) as connection:
            rows = connection.execute(_LIST_SQL, parameters).fetchall()
    except psycopg.Error as exc:
        logger.exception("Denetim günlüğü okunamadı")
        raise HTTPException(status_code=503, detail="Denetim günlüğü okunamadı") from exc
    return [AuditEntry(**row) for row in rows]
