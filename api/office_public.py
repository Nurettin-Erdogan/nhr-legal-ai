"""UYAP eklentilerinin belge gönderdiği, bağlantı anahtarıyla (token) korunan herkese açık uç noktalar.

Kimlik doğrulama öncesi tek istisna: anahtar `nhr_app` bağlantısıyla aranır (yalnız sahibi bulmak ve
`last_used_at` yazmak için). Belge yazımı, o sahibin kimliğiyle açılan RLS'li `nhr_runtime` bağlantısıyla
yapılır; yani anahtar yalnız kendi sahibinin verisine yazabilir.

Bu uç noktalar tarayıcı eklentilerinden çağrıldığı için CORS'a her kaynaktan izin verir; çerez taşımaz,
yalnız anahtarla yetkilendirir.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from api.audit import AuditContext, record_event
from api.db import admin_database_connection, authenticated_database_connection
from api.document_indexing import schedule_index
from api.office import _storage_path
from api.uyap_meta import (
    MAX_FILE_BYTES,
    extract_text_sample,
    is_allowed_file,
    parse_uyap_meta,
    safe_file_name,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["office-public"])

# Anahtar JSON gövdesinin içinde olduğundan gövde doğrulamadan önce okunur; tavan kimliksiz
# isteğin tüketebileceği belleği sınırlar (tek dosya 50 MB → base64 ≈ 67 MB, biraz pay).
MAX_INGEST_REQUEST_BYTES = 100 * 1024 * 1024
MULTIPART_OVERHEAD_BYTES = 1024 * 1024

_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


def _reply(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_CORS)


_PLAIN_EVRAK_ID = re.compile(r"[A-Za-z0-9._-]{1,40}")


def evrak_id_prefix(evrak_id: str | None) -> str:
    """Dosya adının başına konan evrak ön eki. UYAP'ın gerçek `evrak_id`si şifreli bir değerdir (tırnak, `/`, `+`
    gibi karakterler taşır; Windows bunları dosya adında kabul etmez ve kayıt "Kayıt hatası" ile düşerdi).
    Düz (sayısal/kısa) kimlik olduğu gibi kullanılır; diğerleri kararlı bir özetle (SHA-256 ilk 12) değiştirilir."""
    value = (evrak_id or "").strip()
    if not value:
        return ""
    if _PLAIN_EVRAK_ID.fullmatch(value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def token_digest(token: str) -> str:
    """Anahtar veritabanında yalnız bu SHA-256 özetiyle saklanır (düz değer tutulmaz)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _owner_for_token(token: str) -> tuple[UUID, UUID] | None:
    """(anahtar kimliği, sahip kimliği) döndürür; anahtar yoksa ya da iptal edilmişse None."""
    if not 20 <= len(token) <= 200:
        return None
    with admin_database_connection() as connection:
        row = connection.execute(
            "SELECT id, owner_id, revoked FROM office_uyap_ingest_tokens WHERE token_hash = %s",
            (token_digest(token),),
        ).fetchone()
        if row is None or row["revoked"]:
            # Sabit süreli karşılaştırma gerekmez (veritabanı araması); yine de ayrım sızdırılmaz.
            return None
        connection.execute(
            "UPDATE office_uyap_ingest_tokens SET last_used_at = %s WHERE id = %s",
            (datetime.now(timezone.utc), row["id"]),
        )
        connection.commit()
        return row["id"], row["owner_id"]


def _schedule_index(owner_id: UUID, document_id: UUID | None, audit: AuditContext) -> None:
    """Yeni belgenin metnini arka planda aranabilir yapar; hata yüklemeyi etkilemez."""
    if document_id is None:
        return
    try:
        schedule_index(owner_id, document_id, audit=audit)
    except Exception:  # noqa: BLE001
        logger.warning("Belge indeksleme zamanlanamadı id=%s", document_id, exc_info=True)


def find_duplicate(
    connection: psycopg.Connection,
    *,
    file_name: str,
    size_bytes: int,
    uyap_file_no: str | None,
    source: str | None,
) -> UUID | None:
    """Aynı belgeyi bulur. Yalnız dosya adı yetmez: farklı davalardaki "dilekce.pdf" ayrı belgedir.

    Ad + boyut + UYAP dosya numarası (boşsa boşla) eşleşirse yinelenen sayılır. RLS nedeniyle yalnız
    çağıranın kendi belgeleri aranır.
    """
    query = (
        "SELECT id FROM office_case_documents WHERE file_name = %s AND size_bytes = %s "
        "AND uyap_file_no IS NOT DISTINCT FROM %s AND deleted_at IS NULL"  # çöpteki belge "yinelenen" değildir
    )
    params: list[Any] = [file_name, size_bytes, uyap_file_no]
    if source is not None:
        query += " AND source = %s"
        params.append(source)
    row = connection.execute(query + " LIMIT 1", params).fetchone()
    return None if row is None else row["id"] if isinstance(row, dict) else row[0]


async def _read_limited_body(request: Request, limit: int) -> bytes | None:
    """İstek gövdesini en çok `limit` bayt okur; aşarsa None. Kimliksiz uçta bellek tavanı sağlar."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _store(
    owner_id: UUID,
    *,
    file_name: str,
    data: bytes,
    source: str,
    mime_type: str | None,
    overrides: dict[str, str | None],
    dedupe_by_source: bool,
    audit: AuditContext,
) -> tuple[str, UUID | None]:
    """Belgeyi diske ve tabloya yazar. ('inserted'|'duplicate'|'failed', kimlik) döndürür."""
    excerpt = " ".join(extract_text_sample(file_name, data).split())
    meta = parse_uyap_meta(file_name, excerpt)
    file_no = overrides.get("uyap_file_no") or meta["uyap_file_no"]
    with authenticated_database_connection(str(owner_id)) as connection:
        existing_id = find_duplicate(
            connection,
            file_name=file_name,
            size_bytes=len(data),
            uyap_file_no=file_no,
            source=source if dedupe_by_source else None,
        )
        if existing_id is not None:
            return "duplicate", existing_id

        key = f"{owner_id}/{datetime.now(timezone.utc).year}/{uuid4()}-{file_name}"
        target = _storage_path(owner_id, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        document_id = uuid4()
        try:
            connection.execute(
                "INSERT INTO office_case_documents (id, owner_id, file_name, storage_path, size_bytes, source, "
                "mime_type, uyap_file_no, uyap_birim, doc_date, doc_type, content_excerpt, uyap_path) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    document_id,
                    owner_id,
                    file_name,
                    key,
                    len(data),
                    source,
                    mime_type,
                    file_no,
                    overrides.get("uyap_birim") or meta["uyap_birim"],
                    meta["doc_date"],
                    overrides.get("doc_type") or meta["doc_type"],
                    excerpt[:4000] or None,
                    overrides.get("uyap_path"),
                ),
            )
            record_event(
                connection,
                action="office.uyap_ingest",
                actor_user_id=owner_id,
                context=audit,
                entity_type="case_document",
                entity_id=document_id,
                metadata={"size": len(data), "source": source},
            )
        except psycopg.Error:
            target.unlink(missing_ok=True)
            raise
        return "inserted", document_id


class IngestFile(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    contentBase64: str = Field(min_length=4, max_length=70 * 1024 * 1024)
    mimeType: str | None = Field(default=None, max_length=120)
    uyapFileNo: str | None = Field(default=None, max_length=60)
    uyapBirim: str | None = Field(default=None, max_length=160)


class IngestRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    source: str = Field(default="uyap-extension", min_length=2, max_length=40)
    files: list[IngestFile] = Field(min_length=1, max_length=25)


@router.options("/uyap-ingest")
@router.options("/v1/documents/upload")
def preflight() -> Response:
    return Response(status_code=204, headers=_CORS)


@router.post("/uyap-ingest")
async def uyap_ingest(request: Request) -> JSONResponse:
    # Gövde, anahtar doğrulanmadan önce okunur (anahtar JSON içinde); bu yüzden pydantic'e
    # bırakmadan, kimliksiz istekler için sabit bir bellek tavanıyla okunur.
    raw = await _read_limited_body(request, MAX_INGEST_REQUEST_BYTES)
    if raw is None:
        return _reply({"error": "İstek çok büyük"}, 413)
    try:
        body = IngestRequest.model_validate_json(raw)
    except ValidationError:
        return _reply({"error": "Geçersiz istek"}, 422)
    return await run_in_threadpool(_ingest, body, request)


def _ingest(body: IngestRequest, request: Request) -> JSONResponse:
    try:
        owner = _owner_for_token(body.token)
    except psycopg.Error:
        logger.exception("UYAP anahtarı doğrulanamadı")
        return _reply({"error": "Servis şu an kullanılamıyor"}, 503)
    if owner is None:
        return _reply({"error": "Geçersiz bağlantı anahtarı"}, 401)
    _, owner_id = owner
    audit = AuditContext.from_request(request)

    inserted = duplicates = skipped = 0
    for item in body.files:
        file_name = safe_file_name(item.name)
        if not is_allowed_file(file_name):
            skipped += 1
            continue
        try:
            data = base64.b64decode(
                item.contentBase64.split(",", 1)[1]
                if item.contentBase64.startswith("data:") and "," in item.contentBase64
                else item.contentBase64,
                validate=False,
            )
        except (binascii.Error, ValueError):
            skipped += 1
            continue
        if not data or len(data) > MAX_FILE_BYTES:
            skipped += 1
            continue
        try:
            outcome, document_id = _store(
                owner_id,
                file_name=file_name,
                data=data,
                source=body.source,
                mime_type=item.mimeType,
                overrides={"uyap_file_no": item.uyapFileNo, "uyap_birim": item.uyapBirim},
                dedupe_by_source=True,
                audit=audit,
            )
        except (psycopg.Error, OSError):
            logger.exception("UYAP belgesi kaydedilemedi")
            skipped += 1
            continue
        if outcome == "inserted":
            inserted += 1
            _schedule_index(owner_id, document_id, audit)
        else:
            duplicates += 1
    return _reply(
        {
            "ok": True,
            "found": len(body.files),
            "inserted": inserted,
            "duplicates": duplicates,
            # Eski istemciler için: eklenmeyen her dosya (yinelenen + geçersiz).
            "skipped": skipped + duplicates,
        }
    )


@router.post("/v1/documents/upload")
async def upload_document(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    token = (authorization or "").removeprefix("Bearer ").removeprefix("bearer ").strip()
    if not 20 <= len(token) <= 200:
        return _reply({"error": "Bağlantı anahtarı eksik"}, 401)
    try:
        owner = await run_in_threadpool(_owner_for_token, token)
    except psycopg.Error:
        logger.exception("UYAP anahtarı doğrulanamadı")
        return _reply({"error": "Servis şu an kullanılamıyor"}, 503)
    if owner is None:
        return _reply({"error": "Geçersiz bağlantı anahtarı"}, 401)
    _, owner_id = owner

    # Çok parçalı gövde, anahtar doğrulandıktan sonra ayrıştırılır; yoksa kimliksiz bir istek
    # devasa bir gövdeyi diske yazdırabilirdi.
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_FILE_BYTES + MULTIPART_OVERHEAD_BYTES:
        return _reply({"error": "Dosya çok büyük"}, 413)
    # Eklentinin "Bağlantıyı dene" düğmesi dosyasız istek gönderir ve 400 + "dosya" bekler:
    # anahtar doğrulandıktan sonra gelen boş/bozuk gövde de aynı biçimde yanıtlanır.
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001 - çok parçalı ayrıştırıcı farklı istisnalar atabilir
        return _reply({"error": "Dosya eksik veya istek gövdesi okunamadı"}, 400)
    file = form.get("file")
    if not isinstance(file, StarletteUploadFile):
        return _reply({"error": "Dosya eksik"}, 400)

    def field(name: str) -> str | None:
        value = form.get(name)
        return value if isinstance(value, str) else None

    evrakAdi, evrakId, evrakTuru = field("evrakAdi"), field("evrakId"), field("evrakTuru")
    dosyaEsasNo, birim, source = field("dosyaEsasNo"), field("birim"), field("source")
    klasorYolu = field("klasorYolu")  # UYAP ağacındaki klasör yolu: "<dosya> / <evrak türü> / <evrak>"

    file_name = safe_file_name((evrakAdi or file.filename or "uyap-evrak.pdf").strip()[:300])
    if not is_allowed_file(file_name):
        return _reply({"error": "Desteklenmeyen dosya türü"}, 415)
    data = await file.read(MAX_FILE_BYTES + 1)
    mime_type = file.content_type
    await form.close()
    if not data:
        return _reply({"error": "Boş dosya"}, 400)
    if len(data) > MAX_FILE_BYTES:
        return _reply({"error": "Dosya çok büyük"}, 413)

    prefix = evrak_id_prefix(evrakId)
    unique_name = f"{prefix}-{file_name}" if prefix else file_name
    try:
        outcome, document_id = await run_in_threadpool(
            _store,
            owner_id,
            file_name=unique_name,
            data=data,
            source=(source or "uyap-avukat-eklentisi").strip()[:40],
            mime_type=mime_type,
            overrides={
                "doc_type": (evrakTuru or "").strip()[:120] or None,
                "uyap_file_no": (dosyaEsasNo or "").strip()[:60] or None,
                "uyap_birim": (birim or "").strip()[:160] or None,
                "uyap_path": " ".join((klasorYolu or "").split())[:400] or None,
            },
            dedupe_by_source=False,
            audit=AuditContext.from_request(request),
        )
    except (psycopg.Error, OSError):
        logger.exception("UYAP belgesi kaydedilemedi")
        return _reply({"error": "Kayıt hatası"}, 500)
    if outcome == "duplicate":
        return _reply({"ok": True, "duplicate": True, "id": str(document_id)})
    _schedule_index(owner_id, document_id, AuditContext.from_request(request))
    return _reply({"ok": True, "id": str(document_id), "name": unique_name})



# --- Siteden gelen başvuru formu (oturumsuz) ------------------------------------------------------

_APPLICATION_WINDOW_SECONDS = 600
_APPLICATION_LIMIT = 5
_application_hits: dict[str, list[float]] = {}


def _rate_limited(key: str) -> bool:
    """Aynı IP'den 10 dakikada en çok 5 başvuru (bellekte; süreç yeniden başlarsa sıfırlanır)."""
    from time import monotonic

    now = monotonic()
    hits = [t for t in _application_hits.get(key, []) if now - t < _APPLICATION_WINDOW_SECONDS]
    if len(hits) >= _APPLICATION_LIMIT:
        _application_hits[key] = hits
        return True
    hits.append(now)
    _application_hits[key] = hits
    if len(_application_hits) > 5000:
        _application_hits.clear()
    return False


class ApplicationRequest(BaseModel):
    ad_soyad: str = Field(min_length=2, max_length=200)
    telefon: str | None = Field(default=None, max_length=40)
    eposta: str | None = Field(default=None, max_length=200)
    hukuk_alani: str | None = Field(default=None, max_length=100)
    konu: str = Field(min_length=3, max_length=2000)
    sohbet_ozeti: str | None = Field(default=None, max_length=20000)


@router.options("/basvuru")
def application_preflight() -> Response:
    return Response(status_code=204, headers=_CORS)


@router.post("/basvuru")
def create_application(body: ApplicationRequest, request: Request) -> JSONResponse:
    from api.db import database_connection

    client_ip = request.client.host if request.client else "?"
    if _rate_limited(client_ip):
        return _reply({"error": "Çok fazla başvuru gönderdiniz, lütfen biraz bekleyin."}, 429)
    if not (body.telefon or body.eposta):
        return _reply({"error": "Telefon ya da e-posta girin"}, 400)
    try:
        # Oturumsuz bağlantı (app.user_id boş): RLS yalnız sahipsiz satır eklemeye izin verir.
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO office_basvurular (id, ad_soyad, telefon, eposta, hukuk_alani, konu, sohbet_ozeti) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    uuid4(),
                    body.ad_soyad.strip(),
                    body.telefon,
                    body.eposta,
                    body.hukuk_alani,
                    body.konu.strip(),
                    body.sohbet_ozeti,
                ),
            )
    except psycopg.Error:
        logger.exception("Başvuru kaydedilemedi")
        return _reply({"error": "Başvurunuz kaydedilemedi, lütfen tekrar deneyin."}, 503)
    return _reply({"ok": True})
