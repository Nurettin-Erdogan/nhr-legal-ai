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

import errno
import logging
import re
import mimetypes
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.audit import AuditContext, record_event
from api.document_indexing import schedule_index
from api.auth.routes import current_user_id
from api.config import get_settings
from api.db import authenticated_database_connection
from api.account_export import build_export
from api.case_summary import extract_facts, load_ready_documents
from api.document_compare import CompareTooLarge, compare_texts
from api.document_organization import organized_documents
from api.upload_stream import Upload, UploadTooLarge, receive_upload, upload_limit
from api.uyap_cases import UYAP_SOURCES, link_document, lock_uyap_owner

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
    "feedback": "office_feedback",
}
# Genel CRUD ucundan ERİŞİLEMEYEN (yalnız özel uçlar yazar: doğrulama sonucu istemci tarafından uydurulamasın) ama KVKK dışa aktarımına
# dahil olan sahip tabloları.
EXPORT_ONLY_TABLES: dict[str, str] = {
    "bureau_decisions": "office_bureau_decisions",
    "document_jobs": "office_document_jobs",
    "uyap_audit_runs": "office_uyap_audit_runs",
    "uyap_case_sync": "office_uyap_case_sync",
    "uyap_case_detail": "office_uyap_case_detail",
    "uyap_account": "office_uyap_accounts",
    "uyap_diagnostics": "office_uyap_diagnostics",
}
# Arayüzün `user_id` dediği sahiplik sütunu bu tablolarda `owner_id`'dir.
_USER_ID_ALIAS = {"legal_documents", "risk_analyses", "call_settings"}
# İstemcinin değiştiremeyeceği sütunlar.
_PROTECTED_UPDATE = {"id", "owner_id", "created_at"}
# Çöp kutusu olan tablolar: çöpteki satır genel uçta görünmez ve değiştirilemez, `deleted_at`
# istemciden yazılamaz, genel uçtan silme yapılamaz. Çöpe taşıma / geri alma / kalıcı silme özel
# uçlardandır (api/office_trash.py): kalıcı silme sohbet cevaplarını da temizlemelidir.
_SOFT_DELETE_COLUMN = {"case_documents": "deleted_at"}
_TABLE_PROTECTED_COLUMNS = {
    "case_documents": {"deleted_at", "uyap_evrak_key", "checksum_sha256"},
    # Özet ve ön ek yalnız tetikleyiciyle yazılır; istemci özet ya da düz değer okuyamaz/yazamaz.
    "uyap_ingest_tokens": {"token_hash", "token_prefix"},
}
_MAX_LIMIT = 1000

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


def _live_rows(where: sql.Composable, table: str) -> sql.Composable:
    """Çöp kutusu olan tablolarda çöpteki satırları genel sorgudan çıkarır."""
    column = _SOFT_DELETE_COLUMN.get(table)
    if column is None:
        return where
    return sql.SQL("({}) AND {} IS NULL").format(where, sql.Identifier(column))


# Müvekkil ve dava kayıtlarının sunucu tarafı doğrulaması: arayüz zaten denetler, ama genel uç doğrudan da çağrılabildiğinden
# (ör. boş ad, uydurma durum, 5000 karakterlik ad) kural burada da uygulanır. Değerler `_value` ile türüne çevrildikten sonra denetlenir.
_CLIENT_TYPES = {"individual", "corporate"}
_CASE_STATUSES = {"active", "pending", "closed"}
_TEXT_LIMITS = {
    "clients": {"full_name": 200, "email": 254, "phone": 40, "address": 500, "national_id": 11, "tax_id": 11, "notes": 10000},
    "cases": {"title": 300, "case_no": 100, "esas_no": 100, "court": 300, "case_type": 100, "opponent": 300, "notes": 10000},
    "projects": {"name": 200, "description": 5000},
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# Arayüzün kabul ettiği uzantılarla aynı liste (web/src/lib/uyap.ts ALLOWED_EXTENSIONS): sunucu da yalnız bunları saklar.
_ALLOWED_EXTENSIONS = frozenset(
    "pdf udf odt docx doc txt html tif tiff jpg jpeg png xml eyp zip rar xls xlsx mp3 mp4 wav m4a wma ogg avi wmv mov mpg mpeg 3gp mkv bmp gif webp rtf ppt pptx ods odp csv eml msg p7s p7m 7z".split()
)
_BAD_FILE_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')


def _validate_file_key(key: str) -> None:
    """Depolama anahtarının dosya adı bölümü: uzunluk ve işletim sistemlerinin kabul etmediği karakterler (503 yerine 400)."""
    name = key.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 200:
        raise HTTPException(status_code=400, detail="Dosya adı boş olamaz ve en fazla 200 karakter olabilir")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in _ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Bu dosya türü desteklenmiyor")
    if _BAD_FILE_NAME.search(name):
        raise HTTPException(status_code=400, detail='Dosya adı şu karakterleri içeremez: < > : " | ? *')


# Görev, takvim ve hatırlatma kayıtları (arayüzün zod şemalarıyla aynı değerler): boş başlık, uydurma durum/öncelik/tür ve
# 5000 karakterlik başlık sunucuda da reddedilir.
_AGENDA_RULES: dict[str, dict[str, Any]] = {
    "tasks": {"title": 300, "text": {"description": 10000},
              "enums": {"status": {"todo", "in_progress", "done"}, "priority": {"low", "medium", "high", "urgent"}}},
    "calendar_events": {"title": 300, "text": {"description": 10000, "location": 300},
                        "enums": {"event_type": {"hearing", "meeting", "task", "deadline", "callback", "other"}}},
    "reminders": {"title": 300, "text": {"note": 5000},
                  "enums": {"channel": {"in_app", "email"}, "status": {"pending", "sent", "done", "cancelled"}}},
}


def _validate_agenda(table: str, prepared: dict[str, Any], *, insert: bool) -> None:
    rules = _AGENDA_RULES[table]
    title = prepared.get("title")
    if (insert or "title" in prepared) and not str(title or "").strip():
        raise HTTPException(status_code=400, detail="Başlık boş olamaz")
    if isinstance(title, str) and len(title) > rules["title"]:
        raise HTTPException(status_code=400, detail=f"Başlık en fazla {rules['title']} karakter olabilir")
    for name, limit in rules["text"].items():
        value = prepared.get(name)
        if isinstance(value, str) and len(value) > limit:
            raise HTTPException(status_code=400, detail=f"{name} en fazla {limit} karakter olabilir")
    for name, allowed in rules["enums"].items():
        value = prepared.get(name)
        if value is not None and value not in allowed:
            raise HTTPException(status_code=400, detail=f"Geçersiz değer: {name}")
    start, end = prepared.get("start_at"), prepared.get("end_at")
    if table == "calendar_events" and start is not None and end is not None:
        try:
            ended_before_start = end < start
        except TypeError:  # saat dilimli ile saat dilimsiz değer karşılaştırılamaz: veritabanı kendi kuralını uygular
            ended_before_start = False
        if ended_before_start:
            raise HTTPException(status_code=400, detail="Bitiş, başlangıçtan önce olamaz")


def _validate_prepared(table: str, prepared: dict[str, Any], *, insert: bool, user_id: UUID | None = None) -> None:
    if table == "case_documents":
        # Belge kaydı yalnız sahibinin kendi depolama klasöründeki bir dosyaya işaret edebilir (başkasının yoluna kayıt açılamaz).
        name = prepared.get("file_name")
        if (insert or "file_name" in prepared) and not str(name or "").strip():
            raise HTTPException(status_code=400, detail="Belge adı boş olamaz")
        if isinstance(name, str) and len(name) > 255:
            raise HTTPException(status_code=400, detail="Belge adı en fazla 255 karakter olabilir")
        path = prepared.get("storage_path")
        if path and user_id is not None:
            try:
                _storage_path(user_id, str(path))
            except HTTPException as exc:
                raise HTTPException(status_code=400, detail="Geçersiz dosya yolu") from exc
        return
    if table in _AGENDA_RULES:
        _validate_agenda(table, prepared, insert=insert)
        return
    limits = _TEXT_LIMITS.get(table)
    if limits is None:
        return
    for name, limit in limits.items():
        value = prepared.get(name)
        if isinstance(value, str) and len(value) > limit:
            raise HTTPException(status_code=400, detail=f"{name} en fazla {limit} karakter olabilir")
    required = {"clients": "full_name", "cases": "title", "projects": "name"}[table]
    if (insert or required in prepared) and not str(prepared.get(required) or "").strip():
        raise HTTPException(status_code=400, detail="Ad/başlık boş olamaz")
    if table == "clients":
        kind = prepared.get("client_type")
        if kind is not None and kind not in _CLIENT_TYPES:
            raise HTTPException(status_code=400, detail="Geçersiz müvekkil tipi")
        email = prepared.get("email")
        if email and not _EMAIL.match(str(email).strip()):
            raise HTTPException(status_code=400, detail="Geçersiz e-posta adresi")
        national = prepared.get("national_id")
        if national and not re.fullmatch(r"\d{11}", str(national)):
            raise HTTPException(status_code=400, detail="TC kimlik numarası 11 haneli olmalı")
        tax = prepared.get("tax_id")
        if tax and not re.fullmatch(r"\d{10,11}", str(tax)):
            raise HTTPException(status_code=400, detail="Vergi numarası 10 ya da 11 haneli olmalı")
    elif table == "projects":
        color = prepared.get("color")
        if color and not _COLOR.match(str(color)):
            raise HTTPException(status_code=400, detail="Geçersiz renk (örn. #C8A24B)")
    else:
        status = prepared.get("status")
        if status is not None and status not in _CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Geçersiz dava durumu")


def _prepare_values(
    values: dict[str, Any], table: str, columns: dict[str, str], user_id: UUID, *, insert: bool
) -> dict[str, Any]:
    prepared: dict[str, Any] = {}
    protected = _TABLE_PROTECTED_COLUMNS.get(table, set())
    for key, raw in values.items():
        name = _column(key, table, columns)
        if name in protected:
            continue  # ör. `deleted_at`: istemci belgeyi çöpe taşıyamaz/çıkaramaz
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


def _run(
    query: OfficeQuery,
    table: str,
    user_id: UUID,
    request: Request,
    new_documents: list[UUID] | None = None,
) -> OfficeResult:
    """`new_documents` verilirse, eklenen ve dosyası olan büro belgelerinin kimlikleri buna yazılır (çağıran okutur)."""
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
                where = _live_rows(where, table)
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
                    if table == "case_documents" and row.get("source") in UYAP_SOURCES:
                        raise HTTPException(status_code=409, detail="UYAP belgesi güvenli aktarım uç noktasından yüklenmelidir.")
                    prepared = _prepare_values(row, table, columns, user_id, insert=True)
                    _validate_prepared(table, prepared, insert=True, user_id=user_id)
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
                    if new_documents is not None and table == "case_documents" and prepared.get("storage_path"):
                        new_documents.append(UUID(str(inserted[-1])))
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
                _validate_prepared(table, prepared, insert=False, user_id=user_id)
                if not prepared:
                    raise HTTPException(status_code=400, detail="Güncellenecek alan yok")
                where, params = _where(query, table, columns)
                where = _live_rows(where, table)
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
                if table in _SOFT_DELETE_COLUMN:
                    raise HTTPException(
                        status_code=409,
                        detail="Bu kayıt çöp kutusuna taşınarak silinir; kalıcı silme çöp kutusundan yapılır.",
                    )
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


async def _receive(file: UploadFile) -> Upload:
    """Yüklemeyi bellek kullanmadan ölçer. Boyut sınırı yoktur; yalnız işletmecinin isteğe bağlı `MAX_UPLOAD_BYTES` ayarı varsa 413."""
    try:
        return await receive_upload(file, upload_limit())
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


def _storage_failure(exc: OSError) -> str:
    if exc.errno == errno.ENOSPC:
        return "Sunucuda disk alanı kalmadı; dosya kaydedilemedi"
    return "Dosya kaydedilemedi; yeniden deneyin"


@router.post("/storage/upload")
async def upload_file(
    key: str,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    target = _storage_path(user_id, key)
    _validate_file_key(key)
    if target.exists():
        raise HTTPException(status_code=409, detail="Bu yolda dosya zaten var")
    upload = await _receive(file)
    try:
        try:
            await run_in_threadpool(upload.place, target)  # geçici dosya + atomik yer değiştirme; bellek kullanmaz
        except OSError as exc:
            logger.exception("Dosya kaydedilemedi")
            raise HTTPException(status_code=503, detail=_storage_failure(exc)) from exc
        size = upload.size
    finally:
        upload.discard()
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            record_event(
                connection,
                action="office.file_upload",
                actor_user_id=user_id,
                context=AuditContext.from_request(request),
                entity_type="office_file",
                metadata={"size": size},
            )
    except psycopg.Error:
        logger.exception("Dosya denetim kaydı yazılamadı")
    return {"key": key, "size": size}


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


def _schedule_document_index(user_id: UUID, document_id: UUID, request: Request) -> None:
    """Metni arka planda aranabilir yapar; hata yüklemeyi asla bozmaz (ask-time taraması yedektir)."""
    try:
        schedule_index(user_id, document_id, audit=AuditContext.from_request(request))
    except Exception:  # noqa: BLE001
        logger.warning("Belge indeksleme zamanlanamadı id=%s", document_id, exc_info=True)


@router.get("/documents/picker")
def document_picker(
    user_id: Annotated[UUID, Depends(current_user_id)],
    case_id: UUID | None = None,
    project_id: UUID | None = None,
    q: str = Query(default="", max_length=255),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
):
    """Bounded metadata only; RLS applies to every page and search."""
    from api.ai.workspace_scope import project_document_predicate

    with authenticated_database_connection(str(user_id)) as connection:
        clauses = ["od.deleted_at IS NULL"]
        params: dict[str, Any] = {"offset": offset, "limit": limit + 1}
        if case_id:
            _case_for_document(connection, case_id)
            clauses.append("od.case_id = %(case_id)s")
            params["case_id"] = case_id
        if project_id:
            if not connection.execute(
                "SELECT id FROM office_projects WHERE id = %s", (project_id,)
            ).fetchone():
                raise HTTPException(status_code=404, detail="Proje bulunamadı")
            clauses.append(project_document_predicate())
            params["office_project_id"] = project_id
        if q.strip():
            # Treat wildcard characters as literal user input.
            params["search"] = "%" + re.sub(r"([\\%_])", r"\\\1", q.strip()) + "%"
            clauses.append(
                "(od.file_name ILIKE %(search)s OR od.uyap_file_no ILIKE %(search)s "
                "OR od.uyap_birim ILIKE %(search)s)"
            )
        rows = connection.execute(
            "SELECT od.id, od.file_name, od.uyap_file_no, od.uyap_birim, od.doc_date, "
            "od.source, CASE WHEN NULLIF(btrim(od.content_excerpt), '') IS NOT NULL "
            "THEN 'ready' WHEN od.created_at > now() - interval '3 minutes' "
            "THEN 'reading' ELSE 'none' END AS text_state "
            "FROM office_case_documents od WHERE " + " AND ".join(clauses)
            + " ORDER BY od.created_at DESC, od.id DESC LIMIT %(limit)s OFFSET %(offset)s",
            params,
        ).fetchall()
    return JSONResponse(
        jsonable_encoder({"documents": rows[:limit], "has_more": len(rows) > limit}),
        headers={"Cache-Control": "no-store"},
    )


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
    upload = None
    try:
        # Önce kısa bir erişim denetimi: yabancı/yok dava için gövde okunmaz ve dosya yazılmaz.
        with authenticated_database_connection(str(user_id)) as connection:
            _case_for_document(connection, case_id)
        upload = await _receive(file)
        if upload.size == 0:
            raise HTTPException(status_code=400, detail="Boş dosya yüklenemez")
        # Dosya, kayıt işleminden ÖNCE yazılır: büyük dosyanın kopyalanması sürerken dava satırı kilitli kalmaz. Kayıt başarısız
        # olursa aşağıda yalnız bu çağrının kendi dosyası silinir.
        try:
            created = True
            await run_in_threadpool(upload.place, target, exclusive=True)
        except OSError as exc:
            if isinstance(exc, FileExistsError):
                created = False  # var olan dosya bu çağrıya ait değildir: silinmez
            raise HTTPException(status_code=503, detail=_storage_failure(exc)) from exc
        with authenticated_database_connection(str(user_id)) as connection:
            case = _case_for_document(connection, case_id)
            connection.execute(
                "INSERT INTO office_case_documents "
                "(id, owner_id, case_id, client_id, file_name, storage_path, mime_type, size_bytes, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'manual')",
                (document_id, user_id, case_id, case["client_id"], name, key,
                 (file.content_type or "application/octet-stream")[:255], upload.size),
            )
            record_event(connection, action="office.case_document_upload", actor_user_id=user_id,
                         context=AuditContext.from_request(request), entity_type="case_documents",
                         entity_id=document_id, metadata={"case_id": str(case_id), "size": upload.size})
            ready_to_commit = True
        _schedule_document_index(user_id, document_id, request)
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
    finally:
        if upload is not None:
            upload.discard()


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
                "WHERE id = %s AND deleted_at IS NULL FOR UPDATE", (document_id,)
            ).fetchone()
            if not document:
                raise HTTPException(status_code=404, detail="Belge bulunamadı veya erişim yetkiniz yok")
            if document["case_id"] == case_id:
                _schedule_document_index(user_id, document_id, request)  # zaten bağlı: eksikse tamamla
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
        # Bağlanan belge arka planda aranabilir yapılır (yalnız ilk soruda yetişmesine bırakılmaz).
        _schedule_document_index(user_id, document_id, request)
        return {"id": document_id, "case_id": case_id}
    except psycopg.Error as exc:
        logger.exception("Case document link failed id=%s", document_id)
        raise HTTPException(status_code=503, detail="Belge bağlantısı kaydedilemedi") from exc


@router.get("/cases/{case_id}/documents/index")
def case_document_index(
    case_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> dict[str, Any]:
    """Dava belgelerinin aranabilirlik durumu: hazır / işleniyor / okunamadı (nedeniyle)."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            _case_for_document(connection, case_id)
            rows = connection.execute(
                "SELECT od.id, od.file_name, d.status, d.processing_error, d.processed_at, "
                "(d.metadata->>'ocr') = 'true' AS ocr, "
                "(SELECT count(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunk_count, "
                "(SELECT count(*) FROM document_chunks c WHERE c.document_id = d.id "
                "   AND c.embedding IS NOT NULL) AS embedded_count "
                "FROM office_case_documents od "
                "LEFT JOIN documents d ON d.office_case_document_id = od.id "
                "WHERE od.case_id = %s AND od.deleted_at IS NULL ORDER BY od.created_at",
                (case_id,),
            ).fetchall()
    except psycopg.Error as exc:
        logger.exception("Case document index status failed case=%s", case_id)
        raise HTTPException(status_code=503, detail="Belge durumları alınamadı") from exc
    # Hiç işlenmemiş belgeler (genel tablo/eklenti yoluyla eklenmiş olabilir) durum sorgulanınca arka
    # planda indekslenmeye başlar; aksi halde "Bekliyor" ilk soruya kadar öylece kalırdı.
    for row in [r for r in rows if r["status"] is None][:10]:
        _schedule_document_index(user_id, row["id"], request)
    documents = [
        {
            "id": row["id"],
            "file_name": row["file_name"],
            # Satır yoksa belge henüz hiç işlenmemiştir.
            "status": row["status"] or "pending",
            "error": row["processing_error"],
            "ocr": bool(row.get("ocr")),
            "chunk_count": row["chunk_count"] or 0,
            "semantic_ready": bool(row["chunk_count"]) and row["embedded_count"] == row["chunk_count"],
            "processed_at": row["processed_at"],
        }
        for row in rows
    ]
    return {
        "case_id": case_id,
        "total": len(documents),
        "ready": sum(1 for item in documents if item["status"] == "ready"),
        "documents": documents,
    }


@router.get("/cases/{case_id}/documents/compare")
def compare_case_documents(
    case_id: UUID,
    left: UUID,
    right: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> dict[str, Any]:
    """Davaya bağlı iki belgenin metin farkı (yapay zekâsız, belirleyici): hangi cümleler değişti, eklendi, silindi."""
    if left == right:
        raise HTTPException(status_code=422, detail="Karşılaştırmak için iki farklı belge seçin")
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            _case_for_document(connection, case_id)
            rows = connection.execute(
                "SELECT od.id, od.file_name, d.id AS document_id, d.status, d.processing_error, "
                "(d.metadata->>'ocr') = 'true' AS ocr "
                "FROM office_case_documents od "
                "LEFT JOIN documents d ON d.office_case_document_id = od.id "
                "WHERE od.case_id = %s AND od.id = ANY(%s) AND od.deleted_at IS NULL",
                (case_id, [left, right]),
            ).fetchall()
            by_id = {row["id"]: row for row in rows}
            if left not in by_id or right not in by_id:
                raise HTTPException(status_code=404, detail="Belge bulunamadı veya bu davaya bağlı değil")
            for side in (left, right):
                row = by_id[side]
                if row["status"] != "ready":
                    reason = row["processing_error"] if row["status"] == "failed" and row["processing_error"] else "henüz işlenmedi"
                    raise HTTPException(status_code=409, detail=f"\"{row['file_name']}\" karşılaştırılamıyor: {reason}")
            texts = {
                side: "\n\n".join(
                    chunk["content"]
                    for chunk in connection.execute(
                        "SELECT content FROM document_chunks WHERE document_id = %s ORDER BY chunk_index",
                        (by_id[side]["document_id"],),
                    ).fetchall()
                )
                for side in (left, right)
            }
            # Okuma işlemi: denetim yazılamasa da karşılaştırma engellenmez. Dosya adı ve içerik günlüğe yazılmaz.
            record_event(connection, action="office.case_document_compare", actor_user_id=user_id,
                         context=AuditContext.from_request(request), entity_type="case_document", entity_id=left,
                         metadata={"case_id": str(case_id), "right_document_id": str(right)}, strict=False)
    except psycopg.Error as exc:
        logger.exception("Case document compare failed case=%s", case_id)
        raise HTTPException(status_code=503, detail="Belgeler karşılaştırılamadı") from exc
    if not texts[left].strip() or not texts[right].strip():
        raise HTTPException(status_code=409, detail="Belgelerden birinde karşılaştırılacak metin yok")
    try:
        result = compare_texts(texts[left], texts[right])
    except CompareTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    def describe(side: UUID) -> dict[str, Any]:
        return {"id": side, "file_name": by_id[side]["file_name"], "ocr": bool(by_id[side]["ocr"])}

    return {"case_id": case_id, "left": describe(left), "right": describe(right), **result}


@router.get("/account/export")
def export_account_data(
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> JSONResponse:
    """KVKK: kullanıcının kendi verilerini JSON olarak indirir (parola/anahtar/iç yol hariç, belge dosyaları dahil değil)."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            data = build_export(connection, user_id, {**TABLES, **EXPORT_ONLY_TABLES})
            record_event(connection, action="account.export", actor_user_id=user_id, context=AuditContext.from_request(request),
                         entity_type="user", entity_id=user_id, metadata={"tables": len(data["office"])}, strict=False)
    except psycopg.Error as exc:
        logger.exception("Account export failed")
        raise HTTPException(status_code=503, detail="Veriler dışa aktarılamadı") from exc
    return JSONResponse(
        jsonable_encoder(data),
        headers={"Content-Disposition": 'attachment; filename="jurisai-verilerim.json"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/cases/{case_id}/documents/facts")
def case_document_facts(
    case_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    """Okunmuş dava belgelerinden belirleyici olgu tablosu (tarih, tutar, esas/karar ve kanun numarası); yapay zekâ yoktur."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            _case_for_document(connection, case_id)
            # Doğrudan Python çağrıları da endpoint varsayılanlarını kullanır.
            page_offset = offset if isinstance(offset, int) else 0
            page_limit = limit if isinstance(limit, int) else 100
            documents = load_ready_documents(connection, case_id, limit=page_limit, offset=page_offset)
            counts = connection.execute(
                "SELECT count(*) AS total, count(*) FILTER (WHERE d.status = 'ready') AS ready "
                "FROM office_case_documents od LEFT JOIN documents d ON d.office_case_document_id = od.id "
                "WHERE od.case_id = %s AND od.deleted_at IS NULL", (case_id,),
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("Case document facts failed case=%s", case_id)
        raise HTTPException(status_code=503, detail="Belge olguları alınamadı") from exc
    return {
        "case_id": case_id,
        "total": counts["total"],
        "ready": counts["ready"],
        "offset": page_offset,
        "has_more": page_offset + len(documents) < counts["ready"],
        "documents": [
            {"id": item["id"], "file_name": item["file_name"], "ocr": item["ocr"], **extract_facts(item["text"])}
            for item in documents
        ],
    }


@router.post("/uyap/import")
async def import_uyap_document(user_id: Annotated[UUID, Depends(current_user_id)], request: Request) -> dict[str, Any]:
    """Authenticated manual import uses the same atomic store as the extension.

    No client owner, checksum or stable evidence identity is accepted. Filename/path
    metadata remains a guess and cannot automatically create a case relationship.
    """
    from api.office_public import _schedule_index, _store, read_document_upload

    fields, name, mime, upload = await read_document_upload(request)
    try:
        try:
            sync_id = UUID(fields["syncRunId"]) if fields.get("syncRunId") else None
        except ValueError as exc:
            raise HTTPException(400, "Geçersiz aktarım kaydı") from exc
        metadata_name = fields.get("path", name)
        if len(metadata_name) > 600:
            raise HTTPException(400, "Belge yolu çok uzun")
        audit = AuditContext.from_request(request)
        try:
            outcome, document_id = await run_in_threadpool(
                _store, user_id, file_name=name, data=upload, source="uyap", mime_type=mime,
                overrides={"metadata_name": metadata_name, "uyap_path": metadata_name[:400]},
                dedupe_by_source=True, audit=audit, sync_run_id=sync_id,
            )
        except (psycopg.Error, OSError) as exc:
            logger.exception("Elle UYAP aktarımı kaydedilemedi")
            raise HTTPException(503, "Belge kaydedilemedi; yeniden deneyin") from exc
    finally:
        upload.discard()
    if outcome == "invalid_sync":
        raise HTTPException(404, "Aktarım kaydı bulunamadı")
    if outcome not in {"inserted", "duplicate"}:
        raise HTTPException(409, "Belge aktarımı tamamlanamadı; mevcut kayıt korundu")
    if outcome == "inserted":
        _schedule_index(user_id, document_id, audit)
    return {"ok": True, "duplicate": outcome == "duplicate", "id": str(document_id)}


@router.post("/uyap/link-cases")
def link_uyap_cases(user_id: Annotated[UUID, Depends(current_user_id)], request: Request,
                    after: UUID | None = None) -> dict[str, Any]:
    """Kullanıcının mevcut UYAP arşivini davalara bağla; elle kurulmuş ilişkileri asla ezme."""
    counts = {"linked": 0, "ambiguous": 0, "client_conflict": 0, "missing_metadata": 0, "already_linked": 0, "unavailable": 0}
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            lock_uyap_owner(connection, user_id)
            rows = connection.execute(
                "SELECT id, uyap_file_no, uyap_birim FROM office_case_documents "
                "WHERE owner_id = %s AND source = ANY(%s) AND case_id IS NULL AND deleted_at IS NULL "
                "AND (%s::uuid IS NULL OR id > %s::uuid) ORDER BY id LIMIT 501",
                (user_id, list(UYAP_SOURCES), after, after),
            ).fetchall()
            for row in rows[:500]:
                outcome = link_document(connection, user_id, row["id"], file_no=row["uyap_file_no"],
                                        birim=row["uyap_birim"], audit=AuditContext.from_request(request))
                counts[outcome] += 1
    except psycopg.Error as exc:
        logger.exception("UYAP dava bağlantıları kurulamadı")
        raise HTTPException(status_code=503, detail="UYAP dava bağlantıları kurulamadı") from exc
    return {**counts, "has_more": len(rows) > 500, "next_cursor": str(rows[499]["id"]) if len(rows) > 500 else None}


@router.post("/cases/{case_id}/documents/{document_id}/reindex", status_code=202)
def reindex_case_document(
    case_id: UUID,
    document_id: UUID,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> dict[str, Any]:
    """Belgeyi açıkça yeniden işletir (ör. başarısız olmuş ya da dosyası değişmiş belge)."""
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            _case_for_document(connection, case_id)
            document = connection.execute(
                "SELECT id FROM office_case_documents WHERE id = %s AND case_id = %s AND deleted_at IS NULL",
                (document_id, case_id),
            ).fetchone()
    except psycopg.Error as exc:
        logger.exception("Case document reindex lookup failed id=%s", document_id)
        raise HTTPException(status_code=503, detail="Belge bulunamadı veya erişilemiyor") from exc
    if not document:
        raise HTTPException(status_code=404, detail="Belge bulunamadı veya erişim yetkiniz yok")
    schedule_index(user_id, document_id, audit=AuditContext.from_request(request), force=True)
    return {"id": document_id, "case_id": case_id, "status": "queued"}


# Specific paths must be registered before the generic table route.
@router.get("/case-documents/search")
def search_case_documents(
    user_id: Annotated[UUID, Depends(current_user_id)],
    q: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    organized: bool = False,
    summary_only: bool = False,
    search_in: Literal["metadata", "content"] = "metadata",
    source: Literal["all", "uyap", "manual"] = "all",
    category: Annotated[str, Query(max_length=60)] = "",
    folder: Annotated[str, Query(max_length=1000)] = "",
    order: Literal["recent", "date_desc", "date_asc"] = "recent",
    account: Annotated[str, Query(max_length=40)] = "",
) -> dict[str, Any]:
    """Sahibin tüm aktif belgelerinde sunucu tarafı arama ve sayfalama."""
    if organized or summary_only or source != "all" or category or folder or order != "recent" or search_in == "content" or account:
        try:
            with authenticated_database_connection(str(user_id)) as connection:
                if search_in == "content":
                    connection.execute("SET LOCAL statement_timeout = '8s'")
                return organized_documents(
                    connection, user_id, q=q, source=source, category=category,
                    folder=folder, order=order, offset=offset, limit=limit, summary_only=summary_only,
                    search_in=search_in, account=account,
                )
        except psycopg.Error:
            logger.exception("Kategorili belge listesi yüklenemedi")
            raise HTTPException(status_code=503, detail="Belge listesi şu an yüklenemiyor") from None
    term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{term}%"
    predicate = (
        "owner_id = %s AND deleted_at IS NULL AND "
        "(file_name ILIKE %s ESCAPE '\\' OR uyap_file_no ILIKE %s ESCAPE '\\' "
        "OR uyap_birim ILIKE %s ESCAPE '\\' OR doc_type ILIKE %s ESCAPE '\\')"
    )
    params = (user_id, pattern, pattern, pattern, pattern)
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            total = connection.execute(
                f"SELECT count(*) AS n FROM office_case_documents WHERE {predicate}", params
            ).fetchone()["n"]
            rows = connection.execute(
                "SELECT id, file_name, storage_path, size_bytes, source, uyap_file_no, uyap_birim, "
                "doc_type, doc_date, case_id, created_at FROM office_case_documents WHERE " + predicate +
                " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            ).fetchall()
    except psycopg.Error:
        logger.exception("Belge listesi aranamadı")
        raise HTTPException(status_code=503, detail="Belge listesi şu an yüklenemiyor") from None
    return {"rows": rows, "total": total}


@router.post("/{table}", response_model=OfficeResult)
def query_table(
    table: str,
    query: OfficeQuery,
    user_id: Annotated[UUID, Depends(current_user_id)],
    request: Request,
) -> OfficeResult:
    new_documents: list[UUID] = []
    result = _run(query, table, user_id, request, new_documents)
    # Dosya penceresinden yüklenen belge bu genel yoldan eklenir; kayıt kalıcı olduktan sonra metni arka planda okunur.
    # Aksi halde belge ilk soruya ya da dosya sayfası açılana kadar okunmadan kalıyor, belge seçme listeleri onu
    # "metin çıkarılamadı" diye gösteriyordu (ölçüldü: 2026-10-06).
    for document_id in new_documents:
        _schedule_document_index(user_id, document_id, request)
    return result
