"""Büro çalışma alanı: müvekkil, dava, görev, takvim, belge ve benzeri sahibine özel tablolar.

Web arayüzü bu tablolara tek bir sorgu uç noktasından (`POST /api/office/{tablo}`) erişir; istemci
tarafındaki `supabase.from(...)` çağrıları bu sözleşmeye çevrilir. Güvenlik katmanları:

* Yalnız `TABLES` içindeki tablolar ve o tabloların gerçek sütunları kabul edilir; sütun adları
  kimlik olarak `psycopg.sql.Identifier` ile, değerler her zaman parametre olarak gönderilir.
* Satırlar RLS ile sahibine bağlıdır (`owner_id = app_current_user_id()`); sahiplik sütunu istemciden
  alınmaz, kullanıcı kimliğiyle ezilir. Güncelleme ve silme de RLS'e tabidir: başkasının satırı
  filtreye uysa bile etkilenmez.
* Yazımlar denetim günlüğüne (içerik olmadan) işlenir.
* Kimlik uygulamada üretilir ve eklenen satır `RETURNING` yerine ayrı bir SELECT ile okunur.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/office", tags=["office"])

# Arayüzdeki (Supabase) tablo adı -> gerçek tablo. Bu sözlük aynı zamanda izin listesidir.
TABLES: dict[str, str] = {
    "clients": "office_clients",
    "cases": "office_cases",
    "tasks": "office_tasks",
    "calendar_events": "office_calendar_events",
    "reminders": "office_reminders",
    "projects": "office_projects",
    "project_notes": "office_project_notes",
    "ai_outputs": "office_ai_outputs",
    "calls": "office_calls",
    "call_settings": "office_call_settings",
    "legal_documents": "office_legal_documents",
    "risk_analyses": "office_risk_analyses",
    "basvurular": "office_basvurular",
    "uyap_sync_runs": "office_uyap_sync_runs",
    "case_documents": "office_case_documents",
    "uyap_ingest_tokens": "office_uyap_ingest_tokens",
}
# Arayüzün `user_id` dediği sahiplik sütunu bu tablolarda `owner_id`'dir.
_USER_ID_ALIAS = {"legal_documents", "risk_analyses", "call_settings"}
# İstemcinin değiştiremeyeceği sütunlar.
_PROTECTED_UPDATE = {"id", "owner_id", "created_at"}
_MAX_LIMIT = 1000
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

FilterOp = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "is", "like", "ilike"]
_OPERATORS = {
    "eq": "=",
    "neq": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "like": "LIKE",
    "ilike": "ILIKE",
}

_column_cache: dict[str, dict[str, str]] = {}


class Filter(BaseModel):
    col: str = Field(max_length=64)
    op: FilterOp
    val: Any = None
    negate: bool = False


class OrderBy(BaseModel):
    col: str = Field(max_length=64)
    ascending: bool = True


class OfficeQuery(BaseModel):
    op: Literal["select", "insert", "update", "delete", "upsert"]
    columns: str = "*"
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    order: list[OrderBy] = Field(default_factory=list, max_length=5)
    limit: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    values: dict[str, Any] | list[dict[str, Any]] | None = None
    on_conflict: str | None = Field(default=None, max_length=64)
    single: Literal["one", "maybe"] | None = None
    count: bool = False


class OfficeResult(BaseModel):
    data: Any = None
    count: int | None = None


def _table(name: str) -> str:
    physical = TABLES.get(name)
    if physical is None:
        raise HTTPException(status_code=404, detail="Bilinmeyen tablo")
    return physical


def _columns(connection: psycopg.Connection, physical: str) -> dict[str, str]:
    """Tablonun sütunları ve veri türleri (yalnız ilk kullanımda okunur)."""
    cached = _column_cache.get(physical)
    if cached is not None:
        return cached
    rows = connection.execute(
        "SELECT column_name, data_type, udt_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
        (physical,),
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=503, detail="Tablo şeması okunamadı")
    result = {
        row["column_name"]: ("jsonb" if row["data_type"] in ("json", "jsonb") else row["udt_name"])
        for row in rows
    }
    _column_cache[physical] = result
    return result


def _column(name: str, table: str, columns: dict[str, str]) -> str:
    if name == "user_id" and table in _USER_ID_ALIAS:
        name = "owner_id"
    if name not in columns:
        raise HTTPException(status_code=400, detail=f"Bilinmeyen sütun: {name[:40]}")
    return name


def _value(kind: str, value: Any) -> Any:
    if kind == "jsonb" and value is not None:
        return Jsonb(value)
    return value


def _select_list(query: OfficeQuery, table: str, columns: dict[str, str]) -> sql.Composable:
    requested = [part.strip() for part in query.columns.split(",") if part.strip()] or ["*"]
    names: list[str] = []
    for part in requested:
        if part == "*":
            names.extend(name for name in columns if name not in names)
        else:
            resolved = _column(part, table, columns)
            if resolved not in names:
                names.append(resolved)
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def _where(query: OfficeQuery, table: str, columns: dict[str, str]) -> tuple[sql.Composable, list[Any]]:
    parts: list[sql.Composable] = []
    params: list[Any] = []
    for item in query.filters:
        name = _column(item.col, table, columns)
        kind = columns[name]
        ident = sql.Identifier(name)
        if item.op == "is":
            keyword = {None: "NULL", True: "TRUE", False: "FALSE"}.get(item.val)
            if keyword is None:
                raise HTTPException(status_code=400, detail="'is' yalnız null/true/false alır")
            clause: sql.Composable = sql.SQL("{} IS {}").format(ident, sql.SQL(keyword))
        elif item.op == "in":
            if not isinstance(item.val, list) or len(item.val) > 500:
                raise HTTPException(status_code=400, detail="'in' en çok 500 değerlik bir liste alır")
            clause = sql.SQL("{} = ANY(%s::{}[])").format(ident, sql.Identifier(kind))
            params.append([str(v) if v is not None else None for v in item.val])
        else:
            clause = sql.SQL("{} {} %s").format(ident, sql.SQL(_OPERATORS[item.op]))
            params.append(_value(kind, item.val))
        parts.append(sql.SQL("NOT ({})").format(clause) if item.negate else clause)
    if not parts:
        return sql.SQL("TRUE"), params
    return sql.SQL(" AND ").join(parts), params


def _rows_out(rows: list[dict[str, Any]], table: str) -> list[dict[str, Any]]:
    if table in _USER_ID_ALIAS:
        for row in rows:
            if "owner_id" in row:
                row["user_id"] = row["owner_id"]
    return rows


def _shape(rows: list[dict[str, Any]], query: OfficeQuery) -> Any:
    if query.single is None:
        return rows
    if len(rows) > 1 or (query.single == "one" and not rows):
        raise HTTPException(status_code=406, detail="Beklenen tek satır bulunamadı")
    return rows[0] if rows else None


def _prepare_values(
    values: dict[str, Any], table: str, columns: dict[str, str], user_id: UUID, *, insert: bool
) -> dict[str, Any]:
    prepared: dict[str, Any] = {}
    for key, raw in values.items():
        name = _column(key, table, columns)
        if not insert and name in _PROTECTED_UPDATE:
            continue
        prepared[name] = _value(columns[name], raw)
    if insert:
        # Sahiplik istemciden alınmaz. Sahipsiz başvuru kaydı yalnız `basvurular` için ve RLS
        # izin verirse (admin) açılabilir.
        if not (table == "basvurular" and "owner_id" in values and values["owner_id"] is None):
            prepared["owner_id"] = user_id
        prepared["id"] = _value("uuid", values.get("id")) or uuid4()
    return prepared


def _fetch_by_ids(
    connection: psycopg.Connection, physical: str, ids: list[UUID], select: sql.Composable
) -> list[dict[str, Any]]:
    if not ids:
        return []
    return connection.execute(
        sql.SQL("SELECT {} FROM {} WHERE id = ANY(%s::uuid[])").format(select, sql.Identifier(physical)),
        (ids,),
    ).fetchall()


def _run(query: OfficeQuery, table: str, user_id: UUID, request: Request) -> OfficeResult:
    physical = _table(table)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            columns = _columns(connection, physical)
            select = _select_list(query, table, columns)
            ident = sql.Identifier(physical)
            affected = 0
            audit_ids: list[UUID] = []

            if query.op == "select":
                where, params = _where(query, table, columns)
                statement = sql.SQL("SELECT {} FROM {} WHERE {}").format(select, ident, where)
                if query.order:
                    statement += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(
                        sql.SQL("{} {}").format(
                            sql.Identifier(_column(o.col, table, columns)),
                            sql.SQL("ASC" if o.ascending else "DESC"),
                        )
                        for o in query.order
                    )
                limit = min(query.limit or _MAX_LIMIT, _MAX_LIMIT)
                if query.single is not None:
                    limit = 2
                statement += sql.SQL(" LIMIT %s OFFSET %s")
                rows = connection.execute(statement, [*params, limit, query.offset]).fetchall()
                total = None
                if query.count:
                    total = connection.execute(
                        sql.SQL("SELECT count(*) AS n FROM {} WHERE {}").format(ident, where), params
                    ).fetchone()["n"]
                return OfficeResult(data=_shape(_rows_out(rows, table), query), count=total)

            if query.op in ("insert", "upsert"):
                if query.values is None:
                    raise HTTPException(status_code=400, detail="values gerekli")
                batch = query.values if isinstance(query.values, list) else [query.values]
                if not batch or len(batch) > 500:
                    raise HTTPException(status_code=400, detail="1-500 satır eklenebilir")
                conflict = _column(query.on_conflict, table, columns) if query.on_conflict else None
                if query.op == "upsert" and conflict is None:
                    raise HTTPException(status_code=400, detail="upsert için on_conflict gerekli")
                inserted: list[UUID] = []
                for row in batch:
                    prepared = _prepare_values(row, table, columns, user_id, insert=True)
                    names = list(prepared)
                    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        ident,
                        sql.SQL(", ").join(sql.Identifier(n) for n in names),
                        sql.SQL(", ").join(sql.Placeholder() for _ in names),
                    )
                    if query.op == "upsert":
                        updates = [n for n in names if n not in _PROTECTED_UPDATE and n != conflict]
                        target = sql.Identifier(conflict)
                        if updates:
                            statement += sql.SQL(" ON CONFLICT ({}) DO UPDATE SET {}").format(
                                target,
                                sql.SQL(", ").join(
                                    sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(n)) for n in updates
                                ),
                            )
                        else:
                            statement += sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(target)
                    connection.execute(statement, [prepared[n] for n in names])
                    inserted.append(prepared["id"])
                    if query.op == "upsert" and conflict:
                        # Çakışmada mevcut satırın kimliği korunur; kimliği geri okumak için anahtarla ara.
                        found = connection.execute(
                            sql.SQL("SELECT id FROM {} WHERE {} = %s").format(ident, sql.Identifier(conflict)),
                            (prepared[conflict],),
                        ).fetchone()
                        if found:
                            inserted[-1] = found["id"]
                affected = len(inserted)
                audit_ids = inserted
                rows = _fetch_by_ids(connection, physical, inserted, select)
                result = OfficeResult(data=_shape(_rows_out(rows, table), query), count=affected)

            elif query.op == "update":
                if not isinstance(query.values, dict) or not query.values:
                    raise HTTPException(status_code=400, detail="values gerekli")
                if not query.filters:
                    raise HTTPException(status_code=400, detail="Filtresiz toplu güncelleme yapılamaz")
                prepared = _prepare_values(query.values, table, columns, user_id, insert=False)
                if not prepared:
                    raise HTTPException(status_code=400, detail="Güncellenecek alan yok")
                where, params = _where(query, table, columns)
                statement = sql.SQL("UPDATE {} SET {} WHERE {} RETURNING {}").format(
                    ident,
                    sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(n)) for n in prepared),
                    where,
                    select,
                )
                rows = connection.execute(statement, [*prepared.values(), *params]).fetchall()
                affected = len(rows)
                audit_ids = [row["id"] for row in rows if "id" in row][:20]
                result = OfficeResult(data=_shape(_rows_out(rows, table), query), count=affected)

            else:  # delete
                if not query.filters:
                    raise HTTPException(status_code=400, detail="Filtresiz toplu silme yapılamaz")
                where, params = _where(query, table, columns)
                deleted = connection.execute(
                    sql.SQL("DELETE FROM {} WHERE {} RETURNING id").format(ident, where), params
                ).fetchall()
                affected = len(deleted)
                audit_ids = [row["id"] for row in deleted][:20]
                result = OfficeResult(data=None, count=affected)

            if affected:
                record_event(
                    connection,
                    action=f"office.{query.op}",
                    actor_user_id=user_id,
                    context=AuditContext.from_request(request),
                    entity_type=table,
                    entity_id=audit_ids[0] if audit_ids else None,
                    metadata={"count": affected},
                )
            return result
    except HTTPException:
        raise
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="Bu kayıt zaten var") from exc
    except psycopg.errors.ForeignKeyViolation as exc:
        raise HTTPException(status_code=409, detail="İlişkili kayıt bulunamadı veya kullanımda") from exc
    except psycopg.errors.InsufficientPrivilege as exc:
        raise HTTPException(status_code=403, detail="Bu kayda erişim yetkiniz yok") from exc
    except (psycopg.errors.DataError, psycopg.errors.IntegrityError) as exc:
        raise HTTPException(status_code=400, detail="Geçersiz veri") from exc
    except psycopg.Error as exc:
        logger.exception("Büro sorgusu başarısız: %s.%s", table, query.op)
        raise HTTPException(status_code=503, detail="Veritabanı isteği başarısız oldu") from exc


# --- Dosya deposu (Supabase Storage yerine yerel disk) -------------------------------------------


def _storage_root() -> Path:
    return (Path(get_settings().document_storage_dir) / "office").resolve()


def _storage_path(user_id: UUID, key: str) -> Path:
    """`<kullanıcı-kimliği>/<dosya>` anahtarını güvenli bir diskteki yola çevirir."""
    parts = [part for part in key.replace("\\", "/").split("/") if part]
    if len(parts) < 2 or parts[0] != str(user_id) or any(part in (".", "..") for part in parts):
        raise HTTPException(status_code=403, detail="Bu dosyaya erişim yetkiniz yok")
    root = _storage_root()
    target = (root / Path(*parts)).resolve()
    if root not in target.parents:
        raise HTTPException(status_code=403, detail="Geçersiz dosya yolu")
    return target


@router.post("/storage/upload")
async def upload_file(
    key: str,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    target = _storage_path(user_id, key)
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Dosya 50 MB sınırını aşıyor")
    if target.exists():
        raise HTTPException(status_code=409, detail="Bu yolda dosya zaten var")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            record_event(
                connection,
                action="office.file_upload",
                actor_user_id=user_id,
                context=AuditContext.from_request(request),
                entity_type="office_file",
                metadata={"size": len(data)},
            )
    except psycopg.Error:
        logger.exception("Dosya denetim kaydı yazılamadı")
    return {"key": key, "size": len(data)}


@router.get("/storage/download")
def download_file(
    key: str, user_id: Annotated[UUID, Depends(current_user_id)]
) -> FileResponse:
    target = _storage_path(user_id, key)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=target.name,
                        headers={"X-Content-Type-Options": "nosniff"})


class RemoveRequest(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=100)


@router.post("/storage/remove")
def remove_files(
    body: RemoveRequest,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> dict[str, int]:
    removed = 0
    for key in body.keys:
        target = _storage_path(user_id, key)
        if target.is_file():
            target.unlink()
            removed += 1
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            record_event(
                connection,
                action="office.file_remove",
                actor_user_id=user_id,
                context=AuditContext.from_request(request),
                entity_type="office_file",
                metadata={"count": removed},
            )
    except psycopg.Error:
        logger.exception("Dosya denetim kaydı yazılamadı")
    return {"removed": removed}


def _case_for_document(connection, case_id: UUID):
    # RLS applies; a foreign case is indistinguishable from a missing one.
    case = connection.execute(
        "SELECT id, client_id FROM office_cases WHERE id = %s FOR SHARE", (case_id,)
    ).fetchone()
    if not case:
        raise HTTPException(status_code=404, detail="Dava bulunamadı veya erişim yetkiniz yok")
    return case


@router.post("/cases/{case_id}/documents", status_code=201)
async def upload_case_document(
    case_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    name = (file.filename or "").replace("\\", "/").split("/")[-1].strip()
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    document_id = uuid4()
    key = f"{user_id}/cases/{case_id}/{document_id}"
    target = _storage_path(user_id, key)
    created = False
    ready_to_commit = False
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            case = _case_for_document(connection, case_id)
            data = await file.read(_MAX_UPLOAD_BYTES + 1)
            if not data:
                raise HTTPException(status_code=400, detail="Boş dosya yüklenemez")
            if len(data) > _MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Dosya 50 MB sınırını aşıyor")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                created = True
                output.write(data)
            connection.execute(
                "INSERT INTO office_case_documents "
                "(id, owner_id, case_id, client_id, file_name, storage_path, mime_type, size_bytes, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual')",
                (document_id, user_id, case_id, case["client_id"], name, key,
                 (file.content_type or "application/octet-stream")[:255], len(data)),
            )
            record_event(connection, action="office.case_document_upload", actor_user_id=user_id,
                         context=AuditContext.from_request(request), entity_type="case_documents",
                         entity_id=document_id, metadata={"case_id": str(case_id), "size": len(data)})
            ready_to_commit = True
        return {"id": document_id, "case_id": case_id, "file_name": name}
    except Exception as exc:
        # A failed COMMIT acknowledgement can still mean the row was committed.
        # Preserve bytes in that ambiguous case; never leave a committed row with a deleted file.
        if created and not ready_to_commit:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                logger.error("Failed to clean up incomplete case upload id=%s", document_id)
        elif created:
            logger.error("Case upload commit uncertain; file retained for reconciliation id=%s", document_id)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, (psycopg.Error, OSError)):
            logger.exception("Case document upload failed id=%s", document_id)
            raise HTTPException(status_code=503, detail="Belge kaydedilemedi; dava evraklarını kontrol edip yeniden deneyin") from exc
        raise


@router.post("/cases/{case_id}/documents/{document_id}/link")
def link_case_document(
    case_id: UUID,
    document_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> dict[str, Any]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            case = _case_for_document(connection, case_id)
            document = connection.execute(
                "SELECT id, case_id, client_id, storage_path FROM office_case_documents "
                "WHERE id = %s FOR UPDATE", (document_id,)
            ).fetchone()
            if not document:
                raise HTTPException(status_code=404, detail="Belge bulunamadı veya erişim yetkiniz yok")
            if document["case_id"] == case_id:
                return {"id": document_id, "case_id": case_id}
            if document["case_id"] is not None:
                raise HTTPException(status_code=409, detail="Belge zaten başka bir davaya bağlı; taşınmadı")
            if document["client_id"] is not None and document["client_id"] != case["client_id"]:
                raise HTTPException(status_code=409, detail="Belgenin müvekkili bu davayla eşleşmiyor; bağlanmadı")
            if not _storage_path(user_id, document["storage_path"]).is_file():
                raise HTTPException(status_code=404, detail="Belgenin fiziksel dosyası bulunamadı")
            connection.execute(
                "UPDATE office_case_documents SET case_id = %s, client_id = %s WHERE id = %s",
                (case_id, case["client_id"], document_id),
            )
            record_event(connection, action="office.case_document_link", actor_user_id=user_id,
                         context=AuditContext.from_request(request), entity_type="case_documents",
                         entity_id=document_id, metadata={"case_id": str(case_id)})
        return {"id": document_id, "case_id": case_id}
    except psycopg.Error as exc:
        logger.exception("Case document link failed id=%s", document_id)
        raise HTTPException(status_code=503, detail="Belge bağlantısı kaydedilemedi") from exc


# Specific paths must be registered before the generic table route.
@router.post("/{table}", response_model=OfficeResult)
def query_table(
    table: str,
    query: OfficeQuery,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> OfficeResult:
    return _run(query, table, user_id, request)
