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
from api.udf import UdfError, extract_udf_text
from api.uyap_meta import (
    MAX_FILE_BYTES,
    extract_text_sample,
    extension_of,
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


class MultipartTooLarge(Exception):
    pass

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


def normalized_repackable_text(file_name: str, data: bytes) -> str | None:
    """Yalnız tam ODT/UDF metnini karşılaştır; PDF/diğerlerinde eksik örnekle evrak atlama."""
    if extension_of(file_name) not in {"odt", "udf"}:
        return None
    try:
        return " ".join(extract_udf_text(data).split()) or None
    except UdfError:
        return None


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
    checksum_sha256: str | None = None,
    evrak_key: str | None = None,
    content_text: str | None = None,
) -> UUID | None:
    """Aynı belgeyi bulur. Yalnız dosya adı yetmez: farklı davalardaki "dilekce.pdf" ayrı belgedir.

    Yeni aktarımda ham içerik özeti ya da kalıcı evrak kimliğiyle birlikte TAM ODT/UDF metni
    eşleşmelidir. Eski özet içermeyen satırların dosyası diskten doğrulanır; kısa metin
    örneğine veya salt ad/boyuta dayanarak farklı belge atlanmaz.
    """
    # UYAP aynı ODT'nin ZIP zaman damgasını/sıkıştırmasını değiştirebilir. Kalıcı evrak
    # kimliği varsa boyutu ön koşul yapma; doğrulanmış metin eşitliğini de kontrol et.
    semantic_check = bool(evrak_key and content_text)
    query = "SELECT id, owner_id, storage_path, checksum_sha256 FROM office_case_documents WHERE file_name = %s"
    params: list[Any] = [file_name]
    if not semantic_check:
        query += " AND size_bytes = %s"
        params.append(size_bytes)
    query += " AND uyap_file_no IS NOT DISTINCT FROM %s AND deleted_at IS NULL"
    params.append(uyap_file_no)
    if source is not None:
        query += " AND source = %s"
        params.append(source)
    if evrak_key is not None:
        query += " AND (uyap_evrak_key IS NULL OR uyap_evrak_key = %s)"
        params.append(evrak_key)
        # Geçiş döneminde anahtarsız eski ve anahtarlı yeni kayıt yan yana olabilir.
        # Önce anahtarlı olanı seç; eski satıra anahtar yazıp unique guard'a çarpma.
        query += " ORDER BY uyap_evrak_key NULLS LAST"
    for row in connection.execute(query, params).fetchall():
        if checksum_sha256 is None:
            return row["id"] if isinstance(row, dict) else row[0]
        stored = row if isinstance(row, dict) else dict(zip(("id", "owner_id", "storage_path", "checksum_sha256"), row))
        if stored["checksum_sha256"] == checksum_sha256:
            return stored["id"]
        if stored["checksum_sha256"] is None or semantic_check:
            try:
                existing_data = _storage_path(stored["owner_id"], stored["storage_path"]).read_bytes()
                if hashlib.sha256(existing_data).hexdigest() == checksum_sha256:
                    return stored["id"]
                if semantic_check and normalized_repackable_text(file_name, existing_data) == content_text:
                    return stored["id"]
            except (OSError, ValueError):
                logger.warning("Eski UYAP belgesinin içeriği doğrulanamadı id=%s", stored["id"])
    return None


def find_identity_conflict(
    connection: psycopg.Connection, file_no: str | None, evrak_key: str | None, source: str
) -> UUID | None:
    if not evrak_key:
        return None
    row = connection.execute(
        "SELECT id FROM office_case_documents WHERE uyap_file_no IS NOT DISTINCT FROM %s "
        "AND uyap_evrak_key = %s AND source = %s AND deleted_at IS NULL LIMIT 1",
        (file_no, evrak_key, source),
    ).fetchone()
    return (row["id"] if isinstance(row, dict) else row[0]) if row else None


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
    evrak_key = evrak_id_prefix(overrides.get("evrak_id")) or None
    checksum = hashlib.sha256(data).hexdigest()
    comparable_text = normalized_repackable_text(file_name, data) if evrak_key else None
    with authenticated_database_connection(str(owner_id)) as connection:
        existing_id = find_duplicate(
            connection,
            file_name=file_name,
            size_bytes=len(data),
            uyap_file_no=file_no,
            source=source if dedupe_by_source else None,
            checksum_sha256=checksum,
            evrak_key=evrak_key,
            content_text=comparable_text,
        )
        if existing_id is not None:
            if evrak_key and find_identity_conflict(connection, file_no, evrak_key, source) is None:
                connection.execute(
                    "UPDATE office_case_documents SET uyap_evrak_key = %s "
                    "WHERE id = %s AND uyap_evrak_key IS NULL",
                    (evrak_key, existing_id),
                )
            return "duplicate", existing_id

        if find_identity_conflict(connection, file_no, evrak_key, source) is not None:
            # Aynı evrak kimliği fakat farklı metin: yeni sürüm sessizce atlanmaz/çoğaltılmaz.
            return "changed", None

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
            inserted = connection.execute(
                "INSERT INTO office_case_documents (id, owner_id, file_name, storage_path, size_bytes, source, "
                "mime_type, uyap_file_no, uyap_birim, doc_date, doc_type, content_excerpt, uyap_path, uyap_evrak_key, checksum_sha256) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
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
                    evrak_key,
                    checksum,
                ),
            )
            if inserted.rowcount == 0:
                target.unlink(missing_ok=True)
                duplicate_id = find_duplicate(
                    connection, file_name=file_name, size_bytes=len(data), uyap_file_no=file_no,
                    source=source if dedupe_by_source else None, checksum_sha256=checksum,
                    evrak_key=evrak_key, content_text=comparable_text,
                )
                if duplicate_id is not None:
                    return "duplicate", duplicate_id
                return ("changed", None) if find_identity_conflict(connection, file_no, evrak_key, source) else ("failed", None)
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
@router.options("/v1/documents/known")
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
        elif outcome == "duplicate":
            duplicates += 1
        else:
            skipped += 1
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
    limit = MAX_FILE_BYTES + MULTIPART_OVERHEAD_BYTES
    received = 0
    original_receive = request.receive

    async def bounded_receive() -> dict[str, Any]:
        nonlocal received
        message = await original_receive()
        received += len(message.get("body", b""))
        if received > limit:
            raise MultipartTooLarge
        return message

    bounded_request = Request(request.scope, receive=bounded_receive)
    try:
        form = await bounded_request.form(max_files=1, max_fields=20, max_part_size=16 * 1024)
    except MultipartTooLarge:
        return _reply({"error": "Dosya çok büyük"}, 413)
    except Exception:  # noqa: BLE001 - çok parçalı ayrıştırıcı farklı istisnalar atabilir
        return _reply({"error": "Dosya eksik veya istek gövdesi okunamadı"}, 400)
    try:
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            return _reply({"error": "Dosya eksik"}, 400)

        def field(name: str) -> str | None:
            value = form.get(name)
            return value if isinstance(value, str) else None

        evrakAdi, evrakId, evrakTuru = field("evrakAdi"), field("evrakId"), field("evrakTuru")
        dosyaEsasNo, birim, source = field("dosyaEsasNo"), field("birim"), field("source")
        klasorYolu = field("klasorYolu")
        file_name = safe_file_name((evrakAdi or file.filename or "uyap-evrak.pdf").strip()[:300])
        if not is_allowed_file(file_name):
            # Uzantı kullanıcıya söylenir (hangi evrak türünün reddedildiği görünsün); dosya adı ve içerik günlüğe yazılmaz.
            rejected = re.sub(r"[^a-z0-9]", "", extension_of(file_name))[:10]
            logger.info("UYAP yüklemesi reddedildi: desteklenmeyen uzantı .%s", rejected or "(yok)")
            return _reply({"error": f"Desteklenmeyen dosya türü (.{rejected})" if rejected else "Desteklenmeyen dosya türü (uzantı yok)"}, 415)
        data = await file.read(MAX_FILE_BYTES + 1)
        mime_type = file.content_type
    finally:
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
                "evrak_id": evrakId,
            },
            dedupe_by_source=False,
            audit=AuditContext.from_request(request),
        )
    except (psycopg.Error, OSError):
        logger.exception("UYAP belgesi kaydedilemedi")
        return _reply({"error": "Kayıt hatası"}, 500)
    if outcome == "duplicate":
        return _reply({"ok": True, "duplicate": True, "id": str(document_id)})
    if outcome == "changed":
        return _reply({"error": "Bu evrakın içeriği değişmiş; mevcut belge korunuyor. Sürümü ayrıca inceleyin."}, 409)
    if outcome != "inserted":
        return _reply({"error": "Kayıt hatası"}, 500)
    _schedule_index(owner_id, document_id, AuditContext.from_request(request))
    return _reply({"ok": True, "id": str(document_id), "name": unique_name})



# --- Daha önce aktarılmış evraklar ----------------------------------------------------------------
# Eklenti, çekmeye başlamadan önce hangi evrakların bu kullanıcının hesabında zaten olduğunu sorar ve onlara hiç
# tıklamaz (yarıda kalan çekmeyi sürdürmek ya da yeniden denemek çok hızlanır). Yalnız anahtar sahibinin kendi
# (çöpte olmayan) belgeleri aranır: RLS'li bağlantı + anahtar doğrulaması.

MAX_KNOWN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_KNOWN_IDS = 5000
MAX_KNOWN_ID_LENGTH = 600
MAX_KNOWN_ROWS = 50000


class KnownRequest(BaseModel):
    evrakIds: list[str] = Field(max_length=MAX_KNOWN_IDS)
    dosyaEsasNo: str | None = Field(default=None, max_length=60)


def known_evrak_ids(evrak_ids: list[str], stored_keys: list[str]) -> list[str]:
    """Yalnız kaydedilmiş açık UYAP evrak kimlikleri bilinir; dosya adından kimlik tahmin edilmez."""
    keys = set(stored_keys)
    known: list[str] = []
    for evrak_id in evrak_ids:
        if not evrak_id or len(evrak_id) > MAX_KNOWN_ID_LENGTH:
            continue
        prefix = evrak_id_prefix(evrak_id)
        if prefix and prefix in keys:
            known.append(evrak_id)
    return known


def stored_keys_on(connection: psycopg.Connection, esas_no: str | None) -> list[str]:
    """Bağlantının (RLS: yalnız çağıranın) çöpte olmayan açık UYAP evrak kimlikleri."""
    rows = connection.execute(
        "SELECT uyap_evrak_key FROM office_case_documents WHERE uyap_file_no IS NOT DISTINCT FROM %s "
        "AND uyap_evrak_key IS NOT NULL AND deleted_at IS NULL LIMIT %s",
        ((esas_no or "").strip()[:60] or None, MAX_KNOWN_ROWS),
    ).fetchall()
    return [row["uyap_evrak_key"] if isinstance(row, dict) else row[0] for row in rows]


def _stored_keys(owner_id: UUID, esas_no: str | None) -> list[str]:
    with authenticated_database_connection(str(owner_id)) as connection:
        return stored_keys_on(connection, esas_no)


@router.post("/v1/documents/known")
async def known_documents(
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

    raw = await _read_limited_body(request, MAX_KNOWN_REQUEST_BYTES)
    if raw is None:
        return _reply({"error": "İstek çok büyük"}, 413)
    try:
        body = KnownRequest.model_validate_json(raw)
    except ValidationError:
        return _reply({"error": "Geçersiz istek"}, 422)
    try:
        keys = await run_in_threadpool(_stored_keys, owner_id, body.dosyaEsasNo)
    except psycopg.Error:
        logger.exception("Bilinen evraklar okunamadı")
        return _reply({"error": "Servis şu an kullanılamıyor"}, 503)
    return _reply({"ok": True, "known": known_evrak_ids(body.evrakIds, keys)})


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
    # KVKK: aydınlatma metni okunmadan kişisel veri alınmaz; sürüm, hangi metnin gösterildiğini kaydeder.
    aydinlatma_okundu: bool = False
    aydinlatma_surum: str | None = Field(default=None, max_length=40)


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
    if not body.aydinlatma_okundu:
        return _reply({"error": "Başvuru için KVKK aydınlatma metnini okuduğunuzu onaylayın"}, 400)
    try:
        # Oturumsuz bağlantı (app.user_id boş): RLS yalnız sahipsiz satır eklemeye izin verir.
        with database_connection() as connection:
            connection.execute(
                "INSERT INTO office_basvurular (id, ad_soyad, telefon, eposta, hukuk_alani, konu, sohbet_ozeti, "
                "kvkk_aydinlatma_at, kvkk_aydinlatma_surum) VALUES (%s, %s, %s, %s, %s, %s, %s, now(), %s)",
                (
                    uuid4(),
                    body.ad_soyad.strip(),
                    body.telefon,
                    body.eposta,
                    body.hukuk_alani,
                    body.konu.strip(),
                    body.sohbet_ozeti,
                    (body.aydinlatma_surum or "")[:40] or None,
                ),
            )
    except psycopg.Error:
        logger.exception("Başvuru kaydedilemedi")
        return _reply({"error": "Başvurunuz kaydedilemedi, lütfen tekrar deneyin."}, 503)
    return _reply({"ok": True})
