"""Denetim günlüğü (KVKK): kim, ne zaman, hangi kaydı üzerinde ne yaptı.

**Olay kaydedilir, içerik kaydedilmez.** Soru/cevap metni, belge içeriği ve dosya adı, e-posta
ya da parola günlüğe yazılmaz; yalnız kimlik numaraları ve sayısal/mantıksal özetler yazılır.
Günlük tek başına kişisel veri deposuna dönüşmemelidir.

İki yazım biçimi vardır:

* `record_event(connection, ...)` çağıranın transaction'ında yazar. `strict=True` (varsayılan)
  iş kaydı ile denetim kaydını ayrılmaz yapar: denetim yazılamazsa iş de geri alınır, denetlenmemiş
  yazım kalmaz. `strict=False` denetimi savepoint içinde dener; hata olursa yalnız loglanır ve iş
  etkilenmez (giriş, çıkış ve AI cevabı gibi kullanılabilirliğin öne çıktığı olaylar).
* `record_event_standalone(...)` kimlik doğrulama öncesi olaylar (başarısız giriş gibi) içindir; kendi
  bağlantısını (`nhr_app`, kimlik doğrulama öncesi sorgu istisnası) açar ve hata olursa loglar.

`activity_logs` üzerinde RLS: INSERT yalnız `actor_user_id = app_current_user_id()` için, SELECT
yalnız kendi kayıtları ya da admin için geçerlidir; UPDATE/DELETE politikası olmadığından uygulama
rolü kayıtları değiştiremez.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import Request
from psycopg.types.json import Jsonb

from api.db import admin_database_connection

logger = logging.getLogger(__name__)

_USER_AGENT_LIMIT = 300

# Eylem adları. Yeni eylem eklerken içeriği değil olayı tarif et.
AUTH_LOGIN = "auth.login"
AUTH_LOGIN_FAILED = "auth.login_failed"
AUTH_REGISTER = "auth.register"
AUTH_LOGOUT = "auth.logout"
PROJECT_CREATE = "project.create"
DOCUMENT_UPLOAD = "document.upload"
CONVERSATION_DELETE = "conversation.delete"
AI_ANSWER = "ai.answer"

_INSERT_SQL = """
INSERT INTO activity_logs (
    id, actor_user_id, action, entity_type, entity_id, project_id,
    request_id, ip_address, user_agent, metadata
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s::inet, %s, %s)
"""


@dataclass(frozen=True, slots=True)
class AuditContext:
    """İsteğin dış bağlamı: aynı isteğin olaylarını ilişkilendiren kimlik, IP ve tarayıcı."""

    request_id: UUID
    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "AuditContext":
        # `X-Forwarded-For` bilinçli olarak okunmaz: güvenilen bir ters vekil yapılandırılmadan
        # istemci bu başlıkla günlüğe istediği IP'yi yazdırabilir.
        host = request.client.host if request.client else None
        return cls(
            request_id=uuid4(),
            ip_address=_valid_ip(host),
            user_agent=_clip_user_agent(request.headers.get("user-agent")),
        )


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _clip_user_agent(value: str | None) -> str | None:
    if not value:
        return None
    return value[:_USER_AGENT_LIMIT]


def email_fingerprint(email: str) -> str:
    """Başarısız girişte e-postayı düz yazmadan aynı adresi tekrar tanımaya yarayan kısa özet."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def record_event(
    connection: psycopg.Connection,
    *,
    action: str,
    actor_user_id: UUID | None,
    context: AuditContext | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    project_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    strict: bool = True,
) -> None:
    """Olayı çağıranın transaction'ına yazar (id uygulamada üretilir, `RETURNING` yok)."""
    parameters = (
        uuid4(),
        actor_user_id,
        action,
        entity_type,
        entity_id,
        project_id,
        context.request_id if context else None,
        context.ip_address if context else None,
        context.user_agent if context else None,
        Jsonb(metadata or {}),
    )
    if strict:
        connection.execute(_INSERT_SQL, parameters)
        return
    try:
        # Savepoint: denetim hatası dıştaki iş transaction'ını bozmaz.
        with connection.transaction():
            connection.execute(_INSERT_SQL, parameters)
    except psycopg.Error:
        logger.exception("Denetim kaydı yazılamadı: %s", action)


def record_event_standalone(
    *,
    action: str,
    actor_user_id: UUID | None = None,
    context: AuditContext | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    project_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Oturum öncesi olaylar için kendi bağlantısıyla, en iyi çaba esasıyla yazar."""
    try:
        with admin_database_connection() as connection, connection.transaction():
            record_event(
                connection,
                action=action,
                actor_user_id=actor_user_id,
                context=context,
                entity_type=entity_type,
                entity_id=entity_id,
                project_id=project_id,
                metadata=metadata,
                strict=True,
            )
    except (psycopg.Error, RuntimeError):
        logger.exception("Denetim kaydı yazılamadı: %s", action)
