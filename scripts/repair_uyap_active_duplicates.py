"""Verify and recoverably trash legacy UYAP repeats for one owner/case.

Dry-run by default. Requires an explicit expected count to apply, and never prints
document text. Files remain in the normal trash retention window.
"""

from __future__ import annotations

import argparse
from uuid import UUID, uuid4

from api.audit import AuditContext
from api.db import admin_database_connection
from api.document_trash import trash_document
from api.office import _storage_path
from api.office_public import normalized_repackable_text


def normalized_text(owner: UUID, path: str, name: str) -> str | None:
    data = _storage_path(owner, path).read_bytes()
    return normalized_repackable_text(name, data)


def verified_pairs(owner: UUID, case_no: str) -> list[tuple[UUID, UUID]]:
    with admin_database_connection() as connection:
        rows = connection.execute(
            "SELECT legacy.id AS old_id, current.id AS new_id, legacy.file_name, "
            "legacy.storage_path AS old_path, current.storage_path AS new_path "
            "FROM office_case_documents legacy JOIN office_case_documents current "
            "ON current.owner_id = legacy.owner_id AND current.uyap_file_no = legacy.uyap_file_no "
            "AND current.file_name = legacy.file_name AND current.source = legacy.source "
            "WHERE legacy.owner_id = %s AND legacy.uyap_file_no = %s "
            "AND legacy.source = 'uyap-avukat-eklentisi' "
            "AND legacy.deleted_at IS NULL AND current.deleted_at IS NULL "
            "AND legacy.case_id IS NULL AND current.case_id IS NULL "
            "AND legacy.uyap_evrak_key IS NULL AND current.uyap_evrak_key IS NOT NULL "
            "AND legacy.checksum_sha256 IS NULL AND current.checksum_sha256 IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM documents d JOIN document_chunks ch ON ch.document_id = d.id "
            "JOIN citations c ON c.document_chunk_id = ch.id WHERE d.office_case_document_id = legacy.id) "
            "ORDER BY legacy.id",
            (owner, case_no),
        ).fetchall()
    pairs: list[tuple[UUID, UUID]] = []
    seen_old: set[UUID] = set()
    seen_new: set[UUID] = set()
    for row in rows:
        old_id, new_id = row["old_id"], row["new_id"]
        if old_id in seen_old or new_id in seen_new:
            raise RuntimeError("Bir evrak birden çok eşleşmeye sahip; otomatik onarım durduruldu")
        seen_old.add(old_id)
        seen_new.add(new_id)
        old = normalized_text(owner, row["old_path"], row["file_name"])
        new = normalized_text(owner, row["new_path"], row["file_name"])
        if not old or old != new:
            raise RuntimeError("Evrak metinleri eşit değil veya okunamadı; otomatik onarım durduruldu")
        pairs.append((old_id, new_id))
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True, type=UUID)
    parser.add_argument("--case-no", required=True)
    parser.add_argument("--expected", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    pairs = verified_pairs(args.owner, args.case_no)
    if len(pairs) != args.expected or args.expected < 1:
        raise RuntimeError(f"Beklenen {args.expected}, doğrulanan {len(pairs)}; hiçbir değişiklik yapılmadı")
    for old_id, new_id in pairs:
        print(f"eski={old_id} tutulan={new_id}")
    if not args.apply:
        print(f"Kuru çalışma: {len(pairs)} doğrulanmış tekrar; değişiklik yapılmadı")
        return
    for old_id, _ in pairs:
        if not trash_document(args.owner, old_id, AuditContext(uuid4())):
            raise RuntimeError(f"Belge çöpe taşınamadı: {old_id}")
    print(f"{len(pairs)} eski tekrar çöp kutusuna taşındı; yeni kayıtlar korundu")


if __name__ == "__main__":
    main()
