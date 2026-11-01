"""Dava belgeleri için çöp kutusu: önce çöpe taşı (geri alınabilir), sonra kalıcı sil.

- **Çöpe taşı**: `office_case_documents.deleted_at` işaretlenir. Belge listelerden, aramadan,
  indekslemeden ve yineleme denetiminden çıkar. Türetilmiş metne dokunulmaz, geri yükleme anlıktır.
- **Kalıcı sil** yalnız çöpteki belge için çalışır (iki adımlı). Belgeye dayanan sohbet cevapları
  belgeden alıntı içerdiğinden önce **temizlenir** (cevap yer tutucuyla değiştirilir, atıflar silinir);
  sonra belge, metni, parçaları ve diskteki dosya silinir. Müvekkil belgesinin silinmesi KVKK ve
  avukatlık sırrı açısından gerçek bir silme olmalıdır; cevaplarda kalan alıntı da silmenin parçasıdır.
- **Süre**: çöpteki belge `OFFICE_TRASH_RETENTION_DAYS` (varsayılan 30) gün sonra kendiliğinden kalıcı silinir.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from api.audit import AuditContext, record_event
from api.db import admin_database_connection, authenticated_database_connection

logger = logging.getLogger(__name__)

RETENTION_DAYS = max(1, int(os.getenv("OFFICE_TRASH_RETENTION_DAYS", "30")))
REDACTED_ANSWER = "Bu cevap, dayandığı belge kalıcı olarak silindiği için kaldırıldı."
ACTION_TRASH = "office.case_document_trash"
ACTION_RESTORE = "office.case_document_restore"
ACTION_DELETE_FOREVER = "office.case_document_delete_forever"


@dataclass(frozen=True, slots=True)
class DeleteOutcome:
    status: str  # deleted | not_found | not_trashed
    redacted_answers: int = 0


def _audit(connection, action: str, owner_id: UUID, document_id: UUID, audit: AuditContext | None, **metadata):
    record_event(
        connection,
        action=action,
        actor_user_id=owner_id,
        context=audit or AuditContext(uuid4()),
        entity_type="case_document",
        entity_id=document_id,
        metadata=metadata,  # dosya adı ve içerik yazılmaz
    )


def trash_document(owner_id: UUID, document_id: UUID, audit: AuditContext | None = None) -> bool:
    """Belgeyi çöpe taşır. Belge yoksa, başkasınınsa ya da zaten çöpteyse False."""
    with authenticated_database_connection(str(owner_id)) as connection:
        moved = connection.execute(
            "UPDATE office_case_documents SET deleted_at = now() WHERE id = %s AND deleted_at IS NULL",
            (document_id,),
        ).rowcount
        if moved:
            _audit(connection, ACTION_TRASH, owner_id, document_id, audit)
    return bool(moved)


def trash_documents(
    owner_id: UUID, document_ids: list[UUID], audit: AuditContext | None = None
) -> list[UUID]:
    """Bir kullanıcının birden çok aktif belgesini tek işlemde çöpe taşır.

    İstemcinin gönderdiği liste güvenilir kabul edilmez: RLS ve ``deleted_at IS NULL``
    koşulu hem başka kullanıcıya ait hem de zaten çöpteki kayıtları sonuçtan çıkarır.
    Her taşınan belge, tekli silmeyle aynı denetim olayıyla kayda geçer. Böylece
    arayüzdeki "tümünü seç" işlemi ağda yüzlerce ayrı istek üretmeden çalışır.
    """
    unique_ids = list(dict.fromkeys(document_ids))
    if not unique_ids:
        return []
    with authenticated_database_connection(str(owner_id)) as connection:
        rows = connection.execute(
            "UPDATE office_case_documents SET deleted_at = now() "
            "WHERE id = ANY(%s) AND deleted_at IS NULL RETURNING id",
            (unique_ids,),
        ).fetchall()
        moved = [row["id"] for row in rows]
        for document_id in moved:
            _audit(connection, ACTION_TRASH, owner_id, document_id, audit, batch=True)
    return moved


def restore_document(owner_id: UUID, document_id: UUID, audit: AuditContext | None = None) -> bool:
    """Belgeyi çöpten geri alır. Çöpte değilse ya da erişilemiyorsa False."""
    with authenticated_database_connection(str(owner_id)) as connection:
        restored = connection.execute(
            "UPDATE office_case_documents SET deleted_at = NULL WHERE id = %s AND deleted_at IS NOT NULL",
            (document_id,),
        ).rowcount
        if restored:
            _audit(connection, ACTION_RESTORE, owner_id, document_id, audit)
    return bool(restored)


def list_trash(owner_id: UUID, case_id: UUID | None = None) -> list[dict]:
    """Çöpteki belgeler; her biri için kalan gün ve kaç sohbet cevabının ona dayandığı."""
    query = (
        "SELECT od.id, od.file_name, od.case_id, od.size_bytes, od.deleted_at, "
        "GREATEST(0, CEIL(EXTRACT(EPOCH FROM (od.deleted_at + make_interval(days => %s) - now())) / 86400))::int "
        "AS days_left, "
        "(SELECT count(DISTINCT ci.message_id) FROM documents d "
        " JOIN document_chunks c ON c.document_id = d.id "
        " JOIN citations ci ON ci.document_chunk_id = c.id "
        " WHERE d.office_case_document_id = od.id) AS cited_answers "
        "FROM office_case_documents od WHERE od.deleted_at IS NOT NULL"
    )
    params: list[object] = [RETENTION_DAYS]
    if case_id is not None:
        query += " AND od.case_id = %s"
        params.append(case_id)
    query += " ORDER BY od.deleted_at DESC LIMIT 200"
    with authenticated_database_connection(str(owner_id)) as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def _remove_file(owner_id: UUID, storage_path: str) -> None:
    # Döngüsel içe aktarmayı önlemek için geç içe aktarılır (api.office bu modülü kullanabilir).
    from api.office import _storage_path

    try:
        _storage_path(owner_id, storage_path).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - dosya silinemese de kayıt silindi; kalan dosya günlüğe yazılır
        logger.warning("Silinen belgenin dosyası kaldırılamadı (elle temizlenmeli) id yolu=%s", storage_path)


def delete_forever(
    owner_id: UUID, document_id: UUID, audit: AuditContext | None = None, *, only_expired: bool = False
) -> DeleteOutcome:
    """Çöpteki belgeyi kalıcı siler; dayandığı sohbet cevaplarını önce temizler.

    `only_expired`: yalnız saklama süresi dolmuş belgeyi siler (otomatik temizlik).
    """
    with authenticated_database_connection(str(owner_id)) as connection:
        row = connection.execute(
            "SELECT storage_path, deleted_at, "
            "(deleted_at IS NOT NULL AND deleted_at < now() - make_interval(days => %s)) AS expired "
            "FROM office_case_documents WHERE id = %s FOR UPDATE",
            (RETENTION_DAYS, document_id),
        ).fetchone()
        if row is None:
            return DeleteOutcome("not_found")
        if row["deleted_at"] is None or (only_expired and not row["expired"]):
            return DeleteOutcome("not_trashed")

        messages = [
            item["message_id"]
            for item in connection.execute(
                "SELECT DISTINCT ci.message_id FROM citations ci "
                "JOIN document_chunks c ON c.id = ci.document_chunk_id "
                "JOIN documents d ON d.id = c.document_id "
                "WHERE d.office_case_document_id = %s",
                (document_id,),
            ).fetchall()
        ]
        if messages:
            # Cevap metni belgeden aynen alıntı içerebilir: yer tutucuyla değiştirilir, atıflar silinir.
            connection.execute("DELETE FROM citations WHERE message_id = ANY(%s)", (messages,))
            connection.execute(
                "UPDATE messages SET content = %s, metadata = metadata || %s WHERE id = ANY(%s) AND role = 'assistant'",
                (REDACTED_ANSWER, Jsonb({"redacted": "source_deleted", "grounded": False}), messages),
            )
        # Türetilmiş belge ve parçaları `ON DELETE CASCADE` ile birlikte silinir.
        connection.execute("DELETE FROM office_case_documents WHERE id = %s", (document_id,))
        _audit(connection, ACTION_DELETE_FOREVER, owner_id, document_id, audit, redacted_answers=len(messages))
        storage_path = row["storage_path"]

    _remove_file(owner_id, storage_path)
    _clear_answer_cache()
    return DeleteOutcome("deleted", len(messages))


def _clear_answer_cache() -> None:
    # Bellekteki cevap önbelleği silinen belgeden alıntı taşıyabilir.
    try:
        from api.ai.cache import answer_cache

        answer_cache.clear()
    except Exception:  # noqa: BLE001
        logger.warning("Cevap önbelleği temizlenemedi", exc_info=True)


def purge_expired(limit: int = 200) -> int:
    """Saklama süresi dolan çöp belgeleri kalıcı siler; silinen sayıyı döndürür."""
    try:
        with admin_database_connection() as connection:
            rows = connection.execute(
                "SELECT id, owner_id FROM office_case_documents "
                "WHERE deleted_at IS NOT NULL AND deleted_at < now() - make_interval(days => %s) "
                "ORDER BY deleted_at LIMIT %s",
                (RETENTION_DAYS, limit),
            ).fetchall()
    except (psycopg.Error, RuntimeError):
        logger.warning("Süresi dolan çöp belgeler listelenemedi", exc_info=True)
        return 0
    purged = 0
    for row in rows:
        try:
            if delete_forever(row["owner_id"], row["id"], only_expired=True).status == "deleted":
                purged += 1
        except psycopg.Error:
            logger.warning("Süresi dolan belge silinemedi id=%s", row["id"], exc_info=True)
    if purged:
        logger.info("Çöp kutusundan %s belge kalıcı silindi (saklama süresi doldu)", purged)
    return purged
