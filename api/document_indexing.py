"""Büro dava belgelerini (UYAP dahil) RAG'in belge hattına indeksler.

Dosyanın kaynağı `office_case_documents` kalır. Burada metin çıkarılır, parçalanır ve mevcut
`documents` / `document_chunks` tablolarına yazılır (migration 030). Türetilen belge
`project_id IS NULL` ile yaratıldığından RLS gereği yalnız sahibine görünür; tüm okuma/yazma
sahibin kimliğiyle açılan `nhr_runtime` bağlantısıyla yapılır.

İlkeler:
- İçerik değişmediyse yeniden işlenmez (SHA-256).
- Metin çıkarılamayan belge (taranmış PDF, görüntü, bozuk dosya) sessizce "hazır" olmaz:
  `failed` + kullanıcıya gösterilebilir neden yazılır, böylece "aranabilir" sanılmaz.
- Embedding başarısızsa belge yine aranabilir (lexical); embedding sonradan tamamlanır.
- Denetim kaydına dosya adı ve içerik yazılmaz.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import monotonic
from uuid import UUID, uuid4

import psycopg
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from api.audit import AuditContext, record_event
from api.config import get_settings
from api.db import authenticated_database_connection
from api.document_processing import DocumentProcessingError, OcrRequired, process_document

logger = logging.getLogger(__name__)

INDEX_ACTION = "office.document_index"
# Metni okunup aranabilir yapılan dosyanın üst boyutu: içerik bellekte işlenir (en çok 2 iş parçacığı). Bundan büyük dosya
# (ör. uzun ses/video kaydı) yine saklanır ve indirilebilir; yalnız metni çıkarılmaz ve açıkça "aranabilir değil" yazılır.
MAX_INDEXABLE_BYTES = 512 * 1024 * 1024
EMBED_BATCH_SIZE = 16
EXCERPT_CHARS = 1500
_GENERIC_FAILURE = "Belge işlenemedi."

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="office-index")
# Süren iş yeniden planlanmaz: uzun bir OCR sürerken her soru aynı belgeyi kuyruğa eklemesin.
_inflight: set[tuple[UUID, UUID]] = set()
_inflight_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class IndexOutcome:
    status: str  # ready | unchanged | failed | missing | needs_ocr (OCR arka plana bırakıldı)
    chunk_count: int = 0
    error: str | None = None


def _read_source(owner_id: UUID, storage_path: str) -> bytes:
    # Döngüsel içe aktarmayı önlemek için geç içe aktarılır (api.office bu modülü çağırır).
    from api.office import _storage_path

    path = _storage_path(owner_id, storage_path)
    size = path.stat().st_size
    if size > MAX_INDEXABLE_BYTES:
        raise DocumentProcessingError("Dosya saklandı; boyutu nedeniyle metni okunup aranabilir yapılmadı.")
    if size == 0:
        raise DocumentProcessingError("Yüklenen dosya boş.")
    return path.read_bytes()


def _write_result(
    owner_id: UUID,
    office_document_id: UUID,
    *,
    file_name: str,
    storage_path: str,
    mime_type: str | None,
    checksum: str | None,
    size_bytes: int | None,
    status: str,
    error: str | None,
    chunks: tuple,
    audit: AuditContext | None,
    force: bool = False,
    ocr: bool = False,
) -> IndexOutcome | None:
    """Türetilmiş belge ve parçalarını tek işlemde yazar. Kaynak belge silinmişse None."""
    with authenticated_database_connection(str(owner_id)) as connection:
        # Aynı belgeyi eşzamanlı indeksleyenleri sıraya sokar; kaynak yoksa/başkasınınsa satır gelmez (RLS).
        source = connection.execute(
            "SELECT id FROM office_case_documents WHERE id = %s AND deleted_at IS NULL FOR UPDATE",
            (office_document_id,),
        ).fetchone()
        if source is None:
            return None
        existing = connection.execute(
            "SELECT id, checksum_sha256, status FROM documents WHERE office_case_document_id = %s",
            (office_document_id,),
        ).fetchone()
        if (
            not force
            and existing is not None
            and status == "ready"
            and existing["status"] == "ready"
            and existing["checksum_sha256"] == checksum
        ):
            # Başka bir işçi aynı içeriği bizden önce indeksledi.
            return IndexOutcome("unchanged")

        # `ocr`: metin OCR ile okundu; okuma hataları olabilir, arayüz bunu belirtir.
        metadata = Jsonb({"origin": "office_case_document", **({"ocr": True} if ocr else {})})
        if existing is None:
            document_id = uuid4()
            connection.execute(
                "INSERT INTO documents (id, project_id, uploaded_by, file_name, mime_type, storage_key, "
                "storage_bucket, status, file_size, checksum_sha256, metadata, processing_error, "
                "processed_at, office_case_document_id) "
                "VALUES (%s, NULL, %s, %s, %s, %s, 'office', %s, %s, %s, %s, %s, NOW(), %s)",
                (document_id, owner_id, file_name, mime_type, storage_path, status, size_bytes,
                 checksum, metadata, error, office_document_id),
            )
        else:
            document_id = existing["id"]
            connection.execute(
                "UPDATE documents SET file_name = %s, mime_type = %s, storage_key = %s, status = %s, "
                "file_size = %s, checksum_sha256 = %s, processing_error = %s, metadata = %s, "
                "processed_at = NOW() WHERE id = %s",
                (file_name, mime_type, storage_path, status, size_bytes, checksum, error, metadata,
                 document_id),
            )
            connection.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))

        if chunks:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO document_chunks (id, document_id, chunk_index, content, page_number, "
                    "section_title, content_hash, metadata) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)",
                    [
                        (uuid4(), document_id, c.index, c.content, c.page_number, c.section_title, c.content_hash)
                        for c in chunks
                    ],
                )
        if status == "ready" and chunks:
            # Belge seçme listeleri "metni var mı" bilgisini bu alandan okur; elle yüklenen belgede boş kalıyordu.
            excerpt = "\n\n".join(chunk.content for chunk in chunks)[:EXCERPT_CHARS]
            connection.execute(
                "UPDATE office_case_documents SET content_excerpt = %s "
                "WHERE id = %s AND (content_excerpt IS NULL OR content_excerpt = '')",
                (excerpt, office_document_id),
            )
        record_event(
            connection,
            action=INDEX_ACTION,
            actor_user_id=owner_id,
            context=audit or AuditContext(uuid4()),
            entity_type="case_document",
            entity_id=office_document_id,
            metadata={"status": status, "chunk_count": len(chunks)},
        )
    return IndexOutcome(status, len(chunks), error)


def index_office_document(
    owner_id: UUID,
    office_document_id: UUID,
    *,
    force: bool = False,
    audit: AuditContext | None = None,
    ocr_mode: str = "run",
) -> IndexOutcome:
    """Bir büro belgesinin metnini indeksler. İçerik aynıysa (ve `force` yoksa) dokunmaz.

    `ocr_mode`: "run" gerekirse OCR yapar (arka plan işi); "defer" OCR gerekiyorsa hiçbir şey yazmadan
    `needs_ocr` döndürür (soru anındaki hızlı yol: dakikalar sürebilecek OCR isteği bekletmesin).
    """
    with authenticated_database_connection(str(owner_id)) as connection:
        source = connection.execute(
            "SELECT file_name, storage_path, mime_type FROM office_case_documents "
            "WHERE id = %s AND deleted_at IS NULL",  # çöpteki belge indekslenmez
            (office_document_id,),
        ).fetchone()
        existing = connection.execute(
            "SELECT checksum_sha256, status FROM documents WHERE office_case_document_id = %s",
            (office_document_id,),
        ).fetchone()
    if source is None:
        return IndexOutcome("missing")

    common = {
        "file_name": source["file_name"],
        "storage_path": source["storage_path"],
        "mime_type": source["mime_type"],
        "audit": audit,
    }
    try:
        data = _read_source(owner_id, source["storage_path"])
    except DocumentProcessingError as exc:
        return _failed(owner_id, office_document_id, common, str(exc), None, None)
    except (OSError, ValueError, HTTPException):
        # `_storage_path` yol güvenliği ihlalinde HTTPException atar; erişilemeyen dosya "bulunamadı" sayılır.
        logger.warning("Büro belgesi dosyası okunamadı id=%s", office_document_id)
        return _failed(owner_id, office_document_id, common, "Belgenin dosyası bulunamadı.", None, None)

    checksum = hashlib.sha256(data).hexdigest()
    if (
        not force
        and existing is not None
        and existing["status"] == "ready"
        and existing["checksum_sha256"] == checksum
    ):
        return IndexOutcome("unchanged")

    try:
        processed = process_document(source["file_name"], data, ocr=ocr_mode)
    except OcrRequired:
        return IndexOutcome("needs_ocr")
    except DocumentProcessingError as exc:
        return _failed(owner_id, office_document_id, common, str(exc), checksum, len(data))
    except Exception:  # noqa: BLE001 - üçüncü taraf ayrıştırıcılar beklenmedik istisna atabilir
        logger.exception("Büro belgesi ayrıştırılamadı id=%s", office_document_id)
        return _failed(owner_id, office_document_id, common, _GENERIC_FAILURE, checksum, len(data))

    outcome = _write_result(
        owner_id, office_document_id, **common, checksum=checksum, size_bytes=len(data),
        status="ready", error=None, chunks=processed.chunks, force=force, ocr=processed.ocr,
    )
    return outcome or IndexOutcome("missing")


def _failed(owner_id, office_document_id, common, error, checksum, size_bytes) -> IndexOutcome:
    outcome = _write_result(
        owner_id, office_document_id, **common, checksum=checksum, size_bytes=size_bytes,
        status="failed", error=error[:500], chunks=(),
    )
    return outcome or IndexOutcome("missing")


def embed_office_document(owner_id: UUID, office_document_id: UUID) -> int:
    """Belgenin embedding'i olmayan parçalarını doldurur; üretilen vektör sayısını döndürür.

    Embedding servisi yoksa 0 döner ve belge lexical olarak aranabilir kalır.
    """
    from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider, vector_literal

    settings = get_settings()
    try:
        provider = create_embedding_provider(
            provider_name=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=settings.ollama_timeout_seconds,
        )
    except EmbeddingProviderError:
        logger.warning("Embedding sağlayıcısı kurulamadı; belge lexical aranacak")
        return 0

    with authenticated_database_connection(str(owner_id)) as connection:
        rows = connection.execute(
            "SELECT c.id, c.content FROM document_chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE d.office_case_document_id = %s AND c.embedding IS NULL ORDER BY c.chunk_index",
            (office_document_id,),
        ).fetchall()

    done = 0
    for start in range(0, len(rows), EMBED_BATCH_SIZE):
        batch = rows[start : start + EMBED_BATCH_SIZE]
        try:
            vectors = provider.embed_documents([row["content"] for row in batch])
            literals = [vector_literal(vector) for vector in vectors]
        except (EmbeddingProviderError, ValueError):
            logger.warning("Belge embedding'i üretilemedi id=%s; sonra tamamlanacak", office_document_id)
            break
        with authenticated_database_connection(str(owner_id)) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    "UPDATE document_chunks SET embedding = %s::vector, embedding_model = %s, "
                    "embedding_created_at = NOW() WHERE id = %s AND embedding IS NULL",
                    [(literal, provider.model, row["id"]) for literal, row in zip(literals, batch)],
                )
        done += len(batch)
    return done


def _index_and_embed(
    owner_id: UUID,
    office_document_id: UUID,
    audit: AuditContext | None,
    force: bool = False,
    ocr_mode: str = "run",
) -> None:
    try:
        outcome = index_office_document(
            owner_id, office_document_id, audit=audit, force=force, ocr_mode=ocr_mode
        )
        if outcome.status == "needs_ocr":
            # Hızlı yolda ertelenen OCR işi: arka planda (OCR açık) yeniden planlanır.
            schedule_index(owner_id, office_document_id, audit=audit, force=force)
        elif outcome.status == "ready":
            embed_office_document(owner_id, office_document_id)
    except Exception:  # noqa: BLE001 - arka plan işi kullanıcı isteğini asla bozmamalı
        logger.exception("Büro belgesi indekslenemedi id=%s", office_document_id)
    finally:
        with _inflight_lock:
            _inflight.discard((owner_id, office_document_id))


def schedule_index(
    owner_id: UUID,
    office_document_id: UUID,
    *,
    audit: AuditContext | None = None,
    force: bool = False,
) -> None:
    """Belgeyi arka planda indeksler. Yükleme isteği bunu beklemez; hata yükleme sonucunu etkilemez."""
    with _inflight_lock:
        if (owner_id, office_document_id) in _inflight:
            return
        _inflight.add((owner_id, office_document_id))
    # İşaret `_index_and_embed` bitince (başarılı ya da hatalı) kaldırılır.
    _executor.submit(_index_and_embed, owner_id, office_document_id, audit, force)


def sweep_unindexed(
    owner_id: UUID,
    *,
    case_id: UUID | None = None,
    limit: int = 5,
    budget_seconds: float = 20.0,
) -> int:
    """Henüz indekslenmemiş belgeleri (hiç denenmemiş) zaman bütçesi içinde indeksler.

    Hangi yoldan eklendiğinden bağımsız çalışır (manuel yükleme, UYAP eklentisi, genel tablo
    ekleme). Başarısız (`failed`) belgeler tekrar denenmez; bunun için açık yeniden indeksleme gerekir.
    Döndürdüğü değer işlenen belge sayısıdır.
    """
    query = (
        "SELECT od.id FROM office_case_documents od "
        "LEFT JOIN documents d ON d.office_case_document_id = od.id "
        "WHERE d.id IS NULL AND od.deleted_at IS NULL"
    )
    params: list[object] = []
    if case_id is not None:
        query += " AND od.case_id = %s"
        params.append(case_id)
    query += " ORDER BY od.created_at LIMIT %s"
    params.append(limit)
    try:
        with authenticated_database_connection(str(owner_id)) as connection:
            pending = [row["id"] for row in connection.execute(query, params).fetchall()]
    except psycopg.Error:
        logger.warning("Bekleyen belgeler listelenemedi", exc_info=True)
        return 0

    deadline = monotonic() + budget_seconds
    processed = 0
    for document_id in pending:
        if monotonic() >= deadline:
            break
        _index_and_embed(owner_id, document_id, None, ocr_mode="defer")
        processed += 1
    return processed


def case_document_coverage(owner_id: UUID, case_id: UUID) -> dict:
    """Bir davadaki belgelerin ne kadarının cevaba katılabildiğini özetler.

    Cevap, okunamayan veya henüz işlenmeyen belgeleri sessizce yok saymamalı: kullanıcı hangi
    belgelerin dikkate alınmadığını bilmelidir. Dosya adları yalnız belgenin sahibine döner.
    """
    with authenticated_database_connection(str(owner_id)) as connection:
        rows = connection.execute(
            "SELECT od.file_name, d.status, d.processing_error, "
            "(d.metadata->>'ocr') = 'true' AS ocr FROM office_case_documents od "
            "LEFT JOIN documents d ON d.office_case_document_id = od.id "
            "WHERE od.case_id = %s AND od.deleted_at IS NULL ORDER BY od.created_at",
            (case_id,),
        ).fetchall()
    ready = sum(1 for row in rows if row["status"] == "ready")
    failed = [
        {"file_name": row["file_name"], "reason": row["processing_error"] or _GENERIC_FAILURE}
        for row in rows
        if row["status"] == "failed"
    ]
    return {
        "case_id": str(case_id),
        "total": len(rows),
        "ready": ready,
        "failed": failed,
        "pending": sum(1 for row in rows if row["status"] not in ("ready", "failed")),
        # OCR ile okunan hazır belgeler: okuma hataları olabilir (tutar, tarih, numara).
        "ocr": sum(1 for row in rows if row["status"] == "ready" and row["ocr"]),
    }
