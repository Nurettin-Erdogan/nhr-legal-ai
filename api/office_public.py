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
import errno
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from api.audit import AuditContext, record_event
from api.db import admin_database_connection, authenticated_database_connection
from api.document_indexing import schedule_index
from api.office import _storage_path
from api.udf import UdfError, extract_udf_text
from api.upload_stream import (
    IN_MEMORY_PARSE_BYTES,
    Upload,
    UploadTooLarge,
    file_sha256,
    receive_upload,
    upload_limit,
)
from api.uyap_account import identity_from_headers, mark, register
from api.uyap_cases import case_number, court_key, link_document, lock_uyap_owner
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

async def read_document_upload(request: Request) -> tuple[dict[str, str], str, str | None, Upload]:
    """Çok parçalı yüklemeyi boyut sınırı olmadan okur. Caller MUST authenticate before calling this.

    Dosya gövdesi belleğe alınmaz: Starlette onu geçici dosyaya yazar (1 MB üstü diskte), burada yalnız ölçülür.
    Dönen `Upload` o geçici dosyayı açık tutar; çağıran işini bitirince `upload.discard()` çağırmalıdır.
    İşletmecinin isteğe bağlı `MAX_UPLOAD_BYTES` ayarı varsa o üst sınır uygulanır (varsayılan: sınır yok).
    """
    limit = upload_limit()
    body_limit = None if limit is None else limit + MULTIPART_OVERHEAD_BYTES
    declared = request.headers.get("content-length", "")
    if body_limit is not None and declared.isdigit() and int(declared) > body_limit:
        raise HTTPException(413, "Dosya çok büyük")
    received = 0
    original_receive = request.receive

    async def bounded_receive() -> dict[str, Any]:
        nonlocal received
        message = await original_receive()
        if body_limit is not None:
            received += len(message.get("body", b""))
            if received > body_limit:
                raise MultipartTooLarge
        return message

    bounded = Request(request.scope, receive=bounded_receive)
    try:
        form = await bounded.form(max_files=1, max_fields=20, max_part_size=16 * 1024)
    except MultipartTooLarge as exc:
        raise HTTPException(413, "Dosya çok büyük") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Dosya eksik veya istek gövdesi okunamadı") from exc
    upload: Upload | None = None
    handed_over = False
    try:
        file = form.get("file")
        if not isinstance(file, StarletteUploadFile):
            raise HTTPException(400, "Dosya eksik")
        fields = {key: value for key, value in form.items() if isinstance(value, str)}
        if any("\x00" in value for value in fields.values()):
            # Identity/court fields must not be silently normalized into a
            # different document identity. Source file bytes are not fields.
            raise HTTPException(400, "Evrak üst verisinde geçersiz NUL karakteri var")
        name = safe_file_name((fields.get("evrakAdi") or file.filename or "uyap-evrak.pdf").strip()[:300])
        archive_only = not is_allowed_file(name)
        if archive_only:
            # Storage is not parsing support. Unknown UYAP attachments are
            # opaque bytes, never executable/inline content or searchable text.
            # Keep this fallback out of anonymous/legacy/general uploads, and
            # require the stable case/document identity used by deduplication.
            if not (0 < len(fields.get("evrakId", "").strip()) <= 600
                    and case_number(fields.get("dosyaEsasNo"))
                    and 0 < len(fields.get("birim", "").strip()) <= 160):
                raise HTTPException(415, "Bilinmeyen tür yalnız dosya/birim ve evrak kimliğiyle arşivlenebilir")
            if extension_of(name) != "bin":
                name = name[:116] + ".bin"
        try:
            upload = await receive_upload(file, limit)
        except UploadTooLarge as exc:
            raise HTTPException(413, str(exc)) from exc
        if upload.size == 0:
            raise HTTPException(400, "Boş dosya")
        if archive_only:
            # A portal error disguised as an unknown attachment must not turn
            # into a successful transfer. Inspect a bounded header, not the file.
            if upload.data is not None:
                header = upload.data[:8192]
            else:
                upload.stream.seek(0)
                header = upload.stream.read(8192)
                upload.stream.seek(0)
            encoding = "utf-16" if header.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            head = header.decode(encoding, errors="replace").lstrip()
            head = re.sub(r"^(?:\s|<!--[\s\S]*?-->)+", "", head)
            if ("html" in (file.content_type or "").lower()
                    or re.match(r"<(?:!doctype\s+html|html|head|body|form|script|div|table|input)\b", head, re.I)
                    or re.match(r"(?:oturum(?:unuz)?\s+(?:sona|kapan|süresi)|giriş\s+yap|doğrulama\s+hatası)", head, re.I)):
                raise HTTPException(415, "Bilinmeyen türdeki yanıt belge olarak doğrulanamadı; HTML/oturum yanıtı arşivlenmedi")
        handed_over = True
        return fields, name, "application/octet-stream" if archive_only else file.content_type, upload
    finally:
        # Başarıda dosya parçası kapatılmaz: `Upload` onun geçici dosyasını kullanır ve `discard()` ile kapatır.
        if not handed_over:
            if upload is not None:
                upload.discard()
            await form.close()


_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-UYAP-Identity, X-UYAP-Identity-Kind, X-UYAP-Portal, X-UYAP-Display",
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


async def _uyap_account(request: Request, owner_id: UUID) -> UUID | JSONResponse:
    """Evrakın geldiği UYAP kişisi (kullanıcı kararı 2026-10-16: dosyalar kimin UYAP'ından geldiyse onun altında dursun).
    Kişi bilinmiyorsa gövde okunmadan reddedilir; aksi halde hesabın UYAP kişileri arasına kaydedilip kimliği döner."""
    identity = identity_from_headers(request.headers)
    if identity is None:
        return _reply({"error": "UYAP'ta giriş yapan kişi okunamadı; eklentiyi güncelleyip UYAP sayfasını yenileyin. "
                                "Dosyalar kimin UYAP'ından geldiği bilinmeden aktarılmaz.",
                       "code": "uyap_identity_required", "retryable": False}, 428)
    try:
        return await run_in_threadpool(register, owner_id, identity, AuditContext.from_request(request))
    except psycopg.Error:
        logger.exception("UYAP kişisi kaydedilemedi")
        return _reply({"error": "Servis şu an kullanılamıyor", "retryable": True}, 503)


async def _mark(owner_id: UUID, account_id: UUID, **target) -> None:
    """Evrakları geldiği UYAP kişisiyle işaretler; hata aktarımı bozmaz (sonraki denetimde yeniden denenir)."""
    try:
        await run_in_threadpool(mark, owner_id, account_id, **target)
    except psycopg.Error:
        logger.warning("UYAP kişisi evraka işlenemedi", exc_info=True)


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
    uyap_birim: str | None = None,
) -> UUID | None:
    """Aynı belgeyi bulur. Yalnız dosya adı yetmez: farklı davalardaki "dilekce.pdf" ayrı belgedir.

    Yeni aktarımda ham içerik özeti ya da kalıcı evrak kimliğiyle birlikte TAM ODT/UDF metni
    eşleşmelidir. Eski özet içermeyen satırların dosyası diskten doğrulanır; kısa metin
    örneğine veya salt ad/boyuta dayanarak farklı belge atlanmaz.
    """
    # UYAP aynı ODT'nin ZIP zaman damgasını/sıkıştırmasını değiştirebilir. Kalıcı evrak
    # kimliği varsa boyutu ön koşul yapma; doğrulanmış metin eşitliğini de kontrol et.
    semantic_check = bool(evrak_key and content_text)
    query = "SELECT id, owner_id, storage_path, checksum_sha256 FROM office_case_documents WHERE "
    if evrak_key:
        # Stable identity survives display-name changes. Unkeyed legacy rows still need the name.
        query += "(uyap_evrak_key = %s OR (uyap_evrak_key IS NULL AND file_name = %s))"
        params: list[Any] = [evrak_key, file_name]
    else:
        query += "file_name = %s"
        params = [file_name]
    if not semantic_check:
        query += " AND size_bytes = %s"
        params.append(size_bytes)
    query += " AND regexp_replace(uyap_file_no, '\\s', '', 'g') IS NOT DISTINCT FROM %s AND deleted_at IS NULL"
    params.append(re.sub(r"\s", "", uyap_file_no) if uyap_file_no else None)
    query += " AND COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\\s+', ' ', 'g')), '') = %s"
    params.append(court_key(uyap_birim))
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
                existing_path = _storage_path(stored["owner_id"], stored["storage_path"])
                if existing_path.stat().st_size > IN_MEMORY_PARSE_BYTES:
                    # Büyük dosya belleğe alınmaz: özet diskten akıtılarak hesaplanır; ODT/UDF metin karşılaştırması
                    # yalnız küçük dosyalara uygulanır (büyük bir ODT/UDF zaten beklenmez).
                    if file_sha256(existing_path) == checksum_sha256:
                        return stored["id"]
                    continue
                existing_data = existing_path.read_bytes()
                if hashlib.sha256(existing_data).hexdigest() == checksum_sha256:
                    return stored["id"]
                if semantic_check and normalized_repackable_text(file_name, existing_data) == content_text:
                    return stored["id"]
            except (OSError, ValueError):
                logger.warning("Eski UYAP belgesinin içeriği doğrulanamadı id=%s", stored["id"])
    return None


def find_identity_conflict(
    connection: psycopg.Connection, file_no: str | None, evrak_key: str | None, source: str,
    birim: str | None = None,
) -> UUID | None:
    if not evrak_key:
        return None
    row = connection.execute(
        "SELECT id FROM office_case_documents WHERE regexp_replace(uyap_file_no, '\\s', '', 'g') IS NOT DISTINCT FROM %s "
        "AND uyap_evrak_key = %s AND source = %s AND deleted_at IS NULL "
        "AND COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\\s+', ' ', 'g')), '') = %s LIMIT 1",
        (re.sub(r"\s", "", file_no) if file_no else None, evrak_key, source, court_key(birim)),
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
    data: bytes | Upload,
    source: str,
    mime_type: str | None,
    overrides: dict[str, str | None],
    dedupe_by_source: bool,
    audit: AuditContext,
    sync_run_id: UUID | None = None,
) -> tuple[str, UUID | None]:
    """Belgeyi diske ve tabloya yazar. ('inserted'|'duplicate'|'failed', kimlik) döndürür.

    `data` küçük içerik için bayt, büyük içerik için `Upload`'tır (boyut sınırı yok; belleğe alınmaz). `Upload` bu işlevin
    sonunda kapatılır.
    """
    upload = data if isinstance(data, Upload) else Upload.from_bytes(data)
    try:
        return _store_upload(
            owner_id, file_name=file_name, upload=upload, source=source, mime_type=mime_type, overrides=overrides,
            dedupe_by_source=dedupe_by_source, audit=audit, sync_run_id=sync_run_id,
        )
    finally:
        upload.discard()


def _store_upload(
    owner_id: UUID,
    *,
    file_name: str,
    upload: Upload,
    source: str,
    mime_type: str | None,
    overrides: dict[str, str | None],
    dedupe_by_source: bool,
    audit: AuditContext,
    sync_run_id: UUID | None,
) -> tuple[str, UUID | None]:
    # Metin örneği ve ODT/UDF karşılaştırması için içerik yalnız makul boyuttaysa belleğe alınır; büyük dosya (ses/video,
    # çok sayfalı tarama paketi) hiç okunmadan saklanır.
    sample = None if extension_of(file_name) == "bin" else upload.small_bytes(IN_MEMORY_PARSE_BYTES)
    excerpt = " ".join(extract_text_sample(file_name, sample).split()) if sample is not None else ""
    meta = parse_uyap_meta(overrides.get("metadata_name") or file_name, excerpt)
    raw_number = overrides.get("uyap_file_no") or meta["uyap_file_no"]
    file_no = case_number(raw_number) or raw_number
    birim = overrides.get("uyap_birim") or meta["uyap_birim"]
    evrak_key = evrak_id_prefix(overrides.get("evrak_id")) or None
    checksum = upload.sha256
    size = upload.size
    comparable_text = normalized_repackable_text(file_name, sample) if evrak_key and sample is not None else None
    with authenticated_database_connection(str(owner_id)) as connection:
        lock_uyap_owner(connection, owner_id)
        if sync_run_id is not None and not connection.execute(
            "SELECT id FROM office_uyap_sync_runs WHERE id=%s AND owner_id=%s", (sync_run_id, owner_id),
        ).fetchone():
            return "invalid_sync", None
        existing_id = find_duplicate(
            connection,
            file_name=file_name,
            size_bytes=size,
            uyap_file_no=file_no,
            source=source if dedupe_by_source else None,
            checksum_sha256=checksum,
            evrak_key=evrak_key,
            content_text=comparable_text,
            uyap_birim=overrides.get("uyap_birim") or meta["uyap_birim"],
        )
        if existing_id is not None:
            link_document(connection, owner_id, existing_id, file_no=overrides.get("uyap_file_no"),
                          birim=overrides.get("uyap_birim"), audit=audit)
            if evrak_key and find_identity_conflict(connection, file_no, evrak_key, source, birim) is None:
                connection.execute(
                    "UPDATE office_case_documents SET uyap_evrak_key = %s "
                    "WHERE id = %s AND uyap_evrak_key IS NULL",
                    (evrak_key, existing_id),
                )
            return "duplicate", existing_id

        if find_identity_conflict(connection, file_no, evrak_key, source, birim) is not None:
            # Aynı evrak kimliği fakat farklı metin: yeni sürüm sessizce atlanmaz/çoğaltılmaz.
            return "changed", None

        key = f"{owner_id}/{datetime.now(timezone.utc).year}/{uuid4()}-{file_name}"
        target = _storage_path(owner_id, key)
        upload.place(target)  # geçici dosya + atomik yer değiştirme; büyük içerik dosyadan dosyaya akıtılır

        document_id = uuid4()
        try:
            inserted = connection.execute(
                "INSERT INTO office_case_documents (id, owner_id, file_name, storage_path, size_bytes, source, "
                "mime_type, uyap_file_no, uyap_birim, doc_date, doc_type, content_excerpt, uyap_path, uyap_evrak_key, checksum_sha256, sync_run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (
                    document_id,
                    owner_id,
                    file_name,
                    key,
                    size,
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
                    sync_run_id,
                ),
            )
            if inserted.rowcount == 0:
                target.unlink(missing_ok=True)
                duplicate_id = find_duplicate(
                    connection, file_name=file_name, size_bytes=size, uyap_file_no=file_no,
                    source=source if dedupe_by_source else None, checksum_sha256=checksum,
                    evrak_key=evrak_key, content_text=comparable_text,
                    uyap_birim=overrides.get("uyap_birim") or meta["uyap_birim"],
                )
                if duplicate_id is not None:
                    link_document(connection, owner_id, duplicate_id, file_no=overrides.get("uyap_file_no"),
                                  birim=overrides.get("uyap_birim"), audit=audit)
                    return "duplicate", duplicate_id
                return ("changed", None) if find_identity_conflict(connection, file_no, evrak_key, source, birim) else ("failed", None)
            record_event(
                connection,
                action="office.uyap_ingest",
                actor_user_id=owner_id,
                context=audit,
                entity_type="case_document",
                entity_id=document_id,
                metadata={"size": size, "source": source},
            )
            # Yalnız portalın açık üst verisi: belge içindeki başka dava numarasından ilişki üretme.
            link_document(connection, owner_id, document_id, file_no=overrides.get("uyap_file_no"),
                          birim=overrides.get("uyap_birim"), audit=audit)
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
    account_id = await _uyap_account(request, owner_id)
    if isinstance(account_id, JSONResponse):
        return account_id

    # Kimlik doğrulama önce yapılır; gövde boyut sınırı olmadan, belleğe alınmadan okunur.
    try:
        fields, file_name, mime_type, upload = await read_document_upload(request)
    except HTTPException as exc:
        return _reply({"error": exc.detail}, exc.status_code)
    evrakId, evrakTuru = fields.get("evrakId"), fields.get("evrakTuru")
    dosyaEsasNo, birim, source = fields.get("dosyaEsasNo"), fields.get("birim"), fields.get("source")
    klasorYolu = fields.get("klasorYolu")

    prefix = evrak_id_prefix(evrakId)
    unique_name = f"{prefix}-{file_name}" if prefix else file_name
    try:
        outcome, document_id = await run_in_threadpool(
            _store,
            owner_id,
            file_name=unique_name,
            data=upload,
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
    except OSError as exc:
        logger.exception("UYAP belgesi kaydedilemedi")
        if exc.errno == errno.ENOSPC:
            return _reply({"error": "Sunucuda disk alanı kalmadı; belge kaydedilemedi", "code": "storage_full", "retryable": False}, 507)
        # Teşhis için yerel yol, evrak içeriği veya anahtar döndürülmez.
        code = "storage_path_invalid" if exc.errno in {errno.EINVAL, errno.ENAMETOOLONG} else "storage_io_error"
        if exc.errno in {errno.EACCES, errno.EPERM}:
            code = "storage_permission_denied"
        return _reply({"error": f"Belge depolanamadı ({code}); sunucu kaydı kontrol edilmeli.", "code": code, "retryable": False}, 500)
    except psycopg.Error as exc:
        logger.exception("UYAP belgesi kaydedilemedi")
        transient = exc.sqlstate in {"57014", "40001", "40P01", "55P03"} or (exc.sqlstate or "").startswith("08")
        code = "database_temporarily_unavailable" if transient else "database_write_error"
        return _reply({"error": f"Belge veritabanına kaydedilemedi ({code}).", "code": code, "retryable": transient}, 503 if transient else 500)
    finally:
        upload.discard()  # sahte/erken dönen `_store` olsa da geçici dosya kalmaz
    archive_info = ({"archiveOnly": True, "searchable": False,
                     "notice": "Özgün dosya arşivlendi; bu türün içeriği aramada kullanılamıyor."}
                    if extension_of(file_name) == "bin" else {})
    if outcome in {"inserted", "duplicate"} and document_id is not None:
        await _mark(owner_id, account_id, document_id=document_id)
    if outcome == "duplicate":
        return _reply({"ok": True, "duplicate": True, "id": str(document_id), **archive_info})
    if outcome == "changed":
        return _reply({"error": "Bu evrakın içeriği değişmiş; mevcut belge korunuyor. Sürümü ayrıca inceleyin."}, 409)
    if outcome != "inserted":
        return _reply({"error": "Belge kaydı doğrulanamadı (document_write_unconfirmed).", "code": "document_write_unconfirmed", "retryable": False}, 500)
    _schedule_index(owner_id, document_id, AuditContext.from_request(request))
    return _reply({"ok": True, "id": str(document_id), "name": unique_name, **archive_info})



# --- Daha önce aktarılmış evraklar ----------------------------------------------------------------
# Eklenti, çekmeye başlamadan önce hangi evrakların bu kullanıcının hesabında zaten olduğunu sorar ve onlara hiç
# tıklamaz (yarıda kalan çekmeyi sürdürmek ya da yeniden denemek çok hızlanır). Yalnız anahtar sahibinin kendi
# (çöpte olmayan) belgeleri aranır: RLS'li bağlantı + anahtar doğrulaması.

MAX_KNOWN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_KNOWN_IDS = 5000
MAX_KNOWN_ID_LENGTH = 600
MAX_KNOWN_ROWS = 250000  # canlıda 20 000+ evraklı dosyalar görüldü (2026-10-17)


class KnownRequest(BaseModel):
    evrakIds: list[str] = Field(max_length=MAX_KNOWN_IDS)
    dosyaEsasNo: str | None = Field(default=None, max_length=60)
    birim: str | None = Field(default=None, max_length=160)


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


def stored_keys_on(connection: psycopg.Connection, esas_no: str | None, birim: str | None = None) -> list[str]:
    """Bağlantının (RLS: yalnız çağıranın) çöpte olmayan açık UYAP evrak kimlikleri."""
    query = (
        "SELECT uyap_evrak_key FROM office_case_documents WHERE regexp_replace(uyap_file_no, '\\s', '', 'g') IS NOT DISTINCT FROM %s "
        "AND uyap_evrak_key IS NOT NULL AND deleted_at IS NULL"
    )
    params: list[Any] = [re.sub(r"\s", "", esas_no) if esas_no else None]
    if birim is not None:
        query += " AND COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\\s+', ' ', 'g')), '') = %s"
        params.append(court_key(birim))
    query += " LIMIT %s"
    params.append(MAX_KNOWN_ROWS)
    rows = connection.execute(query, params).fetchall()
    return [row["uyap_evrak_key"] if isinstance(row, dict) else row[0] for row in rows]


def _stored_keys(owner_id: UUID, esas_no: str | None, birim: str | None = None) -> list[str]:
    with authenticated_database_connection(str(owner_id)) as connection:
        return stored_keys_on(connection, esas_no, birim)


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
    account_id = await _uyap_account(request, owner_id)
    if isinstance(account_id, JSONResponse):
        return account_id

    raw = await _read_limited_body(request, MAX_KNOWN_REQUEST_BYTES)
    if raw is None:
        return _reply({"error": "İstek çok büyük"}, 413)
    try:
        body = KnownRequest.model_validate_json(raw)
    except ValidationError:
        return _reply({"error": "Geçersiz istek"}, 422)
    try:
        # Old clients without a court must re-fetch rather than skip another court's evidence.
        keys = await run_in_threadpool(_stored_keys, owner_id, body.dosyaEsasNo, body.birim) if case_number(body.dosyaEsasNo) and court_key(body.birim) else []
        if keys:
            # Bu dosya bu UYAP kişisinin ağacında görüldü: kimden geldiği bilinmeyen eski evrakları onun adına işaretlenir.
            await _mark(owner_id, account_id, esas_no=body.dosyaEsasNo, birim=body.birim)
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
