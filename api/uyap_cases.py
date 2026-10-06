"""UYAP evraklarını sahibinin davalarına bağlar; esas numarası tek başına kimlik değildir."""

from __future__ import annotations

import re
import unicodedata
from uuid import UUID, uuid4

from api.audit import AuditContext, record_event

UYAP_SOURCES = ("uyap", "uyap-avukat-eklentisi", "uyap-extension")


def case_number(value: str | None) -> str | None:
    match = re.fullmatch(r"\s*(\d{4})\s*/\s*(\d+)\s*", value or "")
    return f"{match[1]}/{match[2]}" if match else None


def court_key(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").translate(str.maketrans("İı", "Ii")).lower().split())


def lock_uyap_owner(connection, owner_id: UUID) -> None:
    """Acquire BEFORE any UYAP insert/row/case lock; serializes only this owner's imports.

    Batches may visit cases in opposite UUID order. A common outer lock prevents
    both advisory cycles and insert-unique-index / document-row lock inversions.
    """
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       (f"uyap-owner:{owner_id}",))


def link_document(connection, owner_id: UUID, document_id: UUID, *, file_no: str | None,
                  birim: str | None, audit: AuditContext) -> str:
    """Açık portal üst verisiyle bağla. Mevcut elle bağlantıları ve belirsiz eşleşmeleri değiştirme.

    Aynı sahibin aynı birim/esas aktarımı transaction kilidiyle tek dava üretir. RLS'ye ek
    sahiplik filtreleri vardır; kimlik uygulamada üretilir, RETURNING kullanılmaz.
    """
    number, court = case_number(file_no), court_key(birim)
    if not number or not court or len(birim or "") > 160:
        return "missing_metadata"
    lock_uyap_owner(connection, owner_id)
    # Önce dava kimliğini kilitle: toplu eşleştirme başka bir evrak satırını beklerken
    # tek-belge yeniden aktarımının aynı dava kilidini beklemesi kilit döngüsü üretmesin.
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                       (f"uyap-case:{owner_id}:{number}:{court}",))
    document = connection.execute(
        "SELECT case_id, source, client_id FROM office_case_documents WHERE id = %s AND owner_id = %s "
        "AND deleted_at IS NULL FOR UPDATE", (document_id, owner_id),
    ).fetchone()
    if not document or document["source"] not in UYAP_SOURCES:
        return "unavailable"
    if document["case_id"] is not None:
        return "already_linked"
    candidates = connection.execute(
        "SELECT id, client_id, court FROM office_cases WHERE owner_id = %s AND "
        "(regexp_replace(case_no, '\\s', '', 'g') = %s OR "
        "regexp_replace(esas_no, '\\s', '', 'g') = %s)", (owner_id, number, number),
    ).fetchall()
    matches = [row for row in candidates if court_key(row["court"]) == court]
    if len(matches) > 1:
        return "ambiguous"
    if matches:
        case_id, client_id = matches[0]["id"], matches[0]["client_id"]
        if document["client_id"] is not None and document["client_id"] != client_id:
            return "client_conflict"
    else:
        # An explicitly assigned document client is not a model/metadata guess.
        case_id, client_id = uuid4(), document["client_id"]
        connection.execute(
            "INSERT INTO office_cases (id, owner_id, client_id, case_no, esas_no, court, title, status, notes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)",
            (case_id, owner_id, client_id, number, number, " ".join((birim or "").split()),
             f"{number} · {' '.join((birim or '').split())}",
             "UYAP evrak aktarımından oluşturuldu. Dosya durumu ve müvekkil ilişkisi henüz doğrulanmadı."),
        )
        record_event(connection, action="office.uyap_case_created", actor_user_id=owner_id,
                     context=audit, entity_type="cases", entity_id=case_id, metadata={})
    connection.execute(
        "UPDATE office_case_documents SET case_id = %s, client_id = COALESCE(client_id, %s) "
        "WHERE id = %s AND owner_id = %s AND case_id IS NULL AND deleted_at IS NULL",
        (case_id, client_id, document_id, owner_id),
    )
    record_event(connection, action="office.uyap_case_linked", actor_user_id=owner_id,
                 context=audit, entity_type="case_document", entity_id=document_id,
                 metadata={"case_id": str(case_id)})
    return "linked"
