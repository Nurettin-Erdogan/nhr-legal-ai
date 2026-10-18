"""Dosyalar kimin UYAP'ından geldiyse onun altında dursun (kullanıcı kararı 2026-10-16).

Bir JurisAI hesabına birden çok kişinin UYAP'ından aktarım yapılabilir. Eklenti, UYAP'ta giriş yapan kişiyi her isteğe ekler;
sunucu bu kişiyi hesabın UYAP kişileri arasına kaydeder ve gelen evrakı onunla işaretler. Belgeler sayfası evrakları bu kişiye
göre ayırır. Kimse engellenmez.

Kimlik numarası sunucuya hiç gelmez: eklenti onu tarayıcıda SHA-256 parmak izine çevirir (`fingerprint`), sunucu bunu gizli bir
anahtarla HMAC'leyip saklar. Görünen ad, UYAP'ın üst köşesindeki ad soyaddır; yalnız hesap sahibi görür (RLS).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from typing import Annotated, Any, Literal
from urllib.parse import unquote
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from api.audit import AuditContext, record_event
from api.auth.routes import current_user_id
from api.db import authenticated_database_connection

logger = logging.getLogger(__name__)

_FINGERPRINT = r"^[0-9a-f]{64}$"
# UYAP'ın üst köşesindeki ad soyad: harf, boşluk, nokta, kesme ve tire (rakam yok: kimlik numarası buraya giremez).
# Yıldız: 2.26.37'nin ilk derlemesi adı maskeli ("Y*** Ü***") gönderiyordu; o eklentiler güncellenene dek kabul edilir.
_DISPLAY = r"^[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû][A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû .'*\-]{0,118}[A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû.*]$"


class UyapIdentity(BaseModel):
    """Eklentinin UYAP sayfasından okuyup gönderdiği kişi: parmak izi + tür + portal + ad soyad."""

    model_config = ConfigDict(extra="forbid")
    fingerprint: str = Field(pattern=_FINGERPRINT)
    kind: Literal["tc", "name"]
    portal: Literal["vatandas", "avukat", "diger"] = "diger"
    display: str = Field(min_length=2, max_length=120, pattern=_DISPLAY)


def _key() -> bytes:
    secret = os.environ.get("UYAP_IDENTITY_SECRET") or os.environ.get("JWT_SECRET") or ""
    if len(secret) < 16:
        raise RuntimeError("UYAP_IDENTITY_SECRET (ya da JWT_SECRET) ayarlı değil")
    # JWT anahtarı doğrudan kullanılmaz: amaca özel türetilmiş anahtar.
    return hashlib.sha256(b"jurisai-uyap-identity:v1:" + secret.encode("utf-8")).digest()


def identity_digest(identity: UyapIdentity) -> str:
    return hmac.new(_key(), f"{identity.kind}:{identity.fingerprint}".encode("ascii"), hashlib.sha256).hexdigest()


def identity_from_headers(headers: Any) -> UyapIdentity | None:
    """Eklentinin `X-UYAP-*` başlıkları; eksik ya da bozuksa None (çağıran reddeder)."""
    try:
        return UyapIdentity(
            fingerprint=(headers.get("x-uyap-identity") or "").strip().lower(),
            kind=(headers.get("x-uyap-identity-kind") or "").strip(),
            portal=(headers.get("x-uyap-portal") or "diger").strip() or "diger",
            # HTTP başlığı ASCII taşır; ad yüzde kodlanmış gelir.
            display=" ".join(unquote((headers.get("x-uyap-display") or "").strip()).split())[:120],
        )
    except Exception:  # noqa: BLE001 - doğrulama hatası "kişi bilinmiyor" demektir
        return None


def register_identity(connection: psycopg.Connection, owner_id: UUID, identity: UyapIdentity,
                      audit: AuditContext | None = None) -> UUID:
    """UYAP kişisini hesabın kişileri arasına kaydeder (varsa adını ve son görülmeyi tazeler); kimliğini döndürür.

    Kimlik uygulamada üretilir; `RETURNING` kullanılmaz (docs/database-setup.md). Bağlantı RLS'lidir.
    """
    digest = identity_digest(identity)
    new_id = uuid4()
    with connection.transaction():
        connection.execute(
            "INSERT INTO office_uyap_accounts (id, owner_id, identity_digest, kind, portal, display_name) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (owner_id, identity_digest) DO UPDATE SET "
            "display_name = EXCLUDED.display_name, portal = EXCLUDED.portal, last_seen_at = clock_timestamp()",
            (new_id, owner_id, digest, identity.kind, identity.portal, identity.display),
        )
    row = connection.execute(
        "SELECT id FROM office_uyap_accounts WHERE owner_id = %s AND identity_digest = %s", (owner_id, digest)
    ).fetchone()
    account_id = row["id"] if isinstance(row, dict) else row[0]
    if account_id == new_id:
        record_event(connection, action="office.uyap_account_added", actor_user_id=owner_id, context=audit,
                     entity_type="uyap_account", entity_id=account_id, metadata={"kind": identity.kind, "portal": identity.portal})
    return account_id


def mark_documents(connection: psycopg.Connection, owner_id: UUID, account_id: UUID, *, document_id: UUID | None = None,
                   esas_no: str | None = None, birim: str | None = None) -> int:
    """Kimden geldiği henüz bilinmeyen evrakları bu UYAP kişisiyle işaretler: tek evrak ya da bir dosyanın (esas no + birim)
    evrakları. Başka bir kişiyle işaretli evrağa dokunulmaz."""
    if document_id is not None:
        return connection.execute(
            "UPDATE office_case_documents SET uyap_account_id = %s WHERE id = %s AND owner_id = %s AND uyap_account_id IS NULL",
            (account_id, document_id, owner_id),
        ).rowcount
    if not esas_no or not birim:
        return 0
    return connection.execute(
        "UPDATE office_case_documents SET uyap_account_id = %s WHERE owner_id = %s AND uyap_account_id IS NULL "
        "AND deleted_at IS NULL AND regexp_replace(uyap_file_no, '\\s', '', 'g') = %s "
        "AND COALESCE(lower(regexp_replace(translate(btrim(uyap_birim), 'İı', 'Ii'), '\\s+', ' ', 'g')), '') = %s",
        (account_id, owner_id, re.sub(r"\s", "", esas_no), _court_key(birim)),
    ).rowcount


def _court_key(birim: str) -> str:
    from api.uyap_cases import court_key

    return court_key(birim)


def register(owner_id: UUID, identity: UyapIdentity, audit: AuditContext | None = None) -> UUID:
    with authenticated_database_connection(str(owner_id)) as connection:
        return register_identity(connection, owner_id, identity, audit)


def mark(owner_id: UUID, account_id: UUID, **target: Any) -> int:
    with authenticated_database_connection(str(owner_id)) as connection:
        return mark_documents(connection, owner_id, account_id, **target)


def _no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/office/uyap/account", tags=["office"], dependencies=[Depends(_no_store)])


@router.get("")
def list_accounts(user_id: Annotated[UUID, Depends(current_user_id)]) -> dict[str, Any]:
    """Bu hesaba aktarım yapılmış UYAP kişileri, dosya ve evrak sayılarıyla; kimden geldiği bilinmeyen UYAP evrakları ayrı."""
    with authenticated_database_connection(str(user_id)) as connection:
        accounts = connection.execute(
            "SELECT a.id, a.display_name, a.kind, a.portal, a.created_at, a.last_seen_at, "
            "count(d.id) AS documents, count(DISTINCT (d.uyap_file_no, d.uyap_birim)) FILTER (WHERE d.id IS NOT NULL) AS files "
            "FROM office_uyap_accounts a LEFT JOIN office_case_documents d ON d.uyap_account_id = a.id AND d.deleted_at IS NULL "
            "WHERE a.owner_id = %s GROUP BY a.id ORDER BY a.created_at",
            (user_id,),
        ).fetchall()
        unknown = connection.execute(
            "SELECT count(*) AS documents, count(DISTINCT (uyap_file_no, uyap_birim)) AS files FROM office_case_documents "
            "WHERE owner_id = %s AND deleted_at IS NULL AND uyap_account_id IS NULL "
            "AND source IN ('uyap', 'uyap-avukat-eklentisi', 'uyap-extension')",
            (user_id,),
        ).fetchone()
    return {
        "accounts": [{"id": str(a["id"]), "display": a["display_name"], "kind": a["kind"], "portal": a["portal"],
                      "files": a["files"], "documents": a["documents"], "added_at": a["created_at"].isoformat(),
                      "last_seen_at": a["last_seen_at"].isoformat()} for a in accounts],
        "unknown": {"files": unknown["files"], "documents": unknown["documents"]},
    }


@router.post("/check")
def check_account(identity: UyapIdentity, user_id: Annotated[UUID, Depends(current_user_id)], request: Request) -> dict[str, Any]:
    """Aktarım başlamadan önce: UYAP'ta giriş yapan kişiyi hesabın kişileri arasına kaydeder (engellemez)."""
    try:
        account_id = register(user_id, identity, AuditContext.from_request(request))
    except psycopg.Error as exc:
        logger.exception("UYAP kişisi kaydedilemedi")
        raise HTTPException(status_code=503, detail="UYAP kişisi kaydedilemedi") from exc
    return {"ok": True, "account_id": str(account_id), "display": identity.display}
