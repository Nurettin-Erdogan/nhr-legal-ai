"""Çalışma alanında genel arama: kullanıcının kendi davaları, müvekkilleri, belgeleri ve görevleri.

Üst menüdeki arama kutusu bunu kullanır. Yalnız oturum sahibinin satırları döner (RLS + açık `owner_id` koşulu);
hukuk korpusu burada aranmaz (onun kendi araması ve doğrulama rozetleri vardır).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office", tags=["office"])

MIN_QUERY_CHARS = 2
PER_GROUP = 5

# Türkçe büyük/küçük harf: `lower()` veritabanı yereline bağlıdır ve "İ/I/ı" çiftlerini tutarlı çevirmez. Arama için hem
# sütun hem terim aynı kurala indirilir: İ, I, ı → i; diğer Türkçe büyük harfler küçüğüne. Böylece "DEMİR", "Demir" ve
# "demır" aynı kaydı bulur.
_FOLD_FROM = "İIıŞÇĞÖÜ"
_FOLD_TO = "iiişçğöü"
_FOLD_TABLE = str.maketrans(_FOLD_FROM, _FOLD_TO)


def fold(text: str) -> str:
    """Aramada kullanılan sadeleştirme: Türkçe harf çiftleri tek biçime, kalanı küçük harfe."""
    return text.translate(_FOLD_TABLE).lower()


def like_pattern(query: str) -> str:
    """Terimi `LIKE` kalıbına çevirir; kullanıcının yazdığı `%`, `_` ve `\\` joker sayılmaz."""
    term = fold(" ".join(query.split()))
    term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{term}%"


def _folded(column: str) -> str:
    return f"lower(translate(coalesce({column}, ''), '{_FOLD_FROM}', '{_FOLD_TO}'))"


def _matches(*columns: str) -> str:
    """Sütunlardan herhangi biri terimi içeriyorsa doğru olan koşul."""
    return "(" + " OR ".join(f"{_folded(column)} LIKE %(pattern)s ESCAPE '\\'" for column in columns) + ")"


_CASES_SQL = f"""
SELECT c.id, c.title, c.case_no, c.esas_no, c.court, c.status, client.full_name AS client_name
FROM office_cases c
LEFT JOIN office_clients client ON client.id = c.client_id
WHERE c.owner_id = %(owner)s
  AND {_matches('c.title', 'c.case_no', 'c.esas_no', 'c.court', 'c.opponent', 'client.full_name')}
ORDER BY c.updated_at DESC, c.id
LIMIT %(limit)s
"""

# Kimlik ve vergi numarasıyla da bulunur, ama numaranın kendisi yanıta konmaz (gereksiz kişisel veri taşınmaz).
_CLIENTS_SQL = f"""
SELECT id, full_name, client_type, phone, email
FROM office_clients
WHERE owner_id = %(owner)s
  AND {_matches('full_name', 'email', 'phone', 'national_id', 'tax_id')}
ORDER BY updated_at DESC, id
LIMIT %(limit)s
"""

_DOCUMENTS_SQL = f"""
SELECT d.id, d.file_name, d.case_id, d.uyap_file_no, d.uyap_birim, d.doc_type, c.title AS case_title
FROM office_case_documents d
LEFT JOIN office_cases c ON c.id = d.case_id
WHERE d.owner_id = %(owner)s AND d.deleted_at IS NULL
  AND {_matches('d.file_name', 'd.uyap_file_no', 'd.uyap_birim', 'd.doc_type')}
ORDER BY d.created_at DESC, d.id
LIMIT %(limit)s
"""

_TASKS_SQL = f"""
SELECT t.id, t.title, t.status, t.due_date, t.case_id, c.title AS case_title
FROM office_tasks t
LEFT JOIN office_cases c ON c.id = t.case_id
WHERE t.owner_id = %(owner)s
  AND {_matches('t.title', 't.description')}
ORDER BY (t.status = 'done'), t.due_date NULLS LAST, t.id
LIMIT %(limit)s
"""


@router.get("/search")
def search_workspace(
    user_id: Annotated[UUID, Depends(current_user_id)],
    q: Annotated[str, Query(max_length=100)] = "",
) -> dict[str, Any]:
    """Oturum sahibinin dava, müvekkil, belge ve görevlerinde arar; her gruptan en çok birkaç kayıt döner."""
    query = " ".join(q.split())
    empty: dict[str, Any] = {"query": query, "cases": [], "clients": [], "documents": [], "tasks": []}
    if len(query) < MIN_QUERY_CHARS:
        return empty
    params = {"owner": user_id, "pattern": like_pattern(query), "limit": PER_GROUP}
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            return {
                "query": query,
                "cases": connection.execute(_CASES_SQL, params).fetchall(),
                "clients": connection.execute(_CLIENTS_SQL, params).fetchall(),
                "documents": connection.execute(_DOCUMENTS_SQL, params).fetchall(),
                "tasks": connection.execute(_TASKS_SQL, params).fetchall(),
            }
    except psycopg.Error:
        logger.exception("Çalışma alanı araması başarısız")
        raise HTTPException(status_code=503, detail="Arama şu an yapılamıyor") from None
