"""Uygulamaya kimlerin girebileceği: herkes ya da yalnız yöneticinin erişim listesindeki e-postalar (migration 062).

Kural veritabanında tek yerdedir (`app_user_access_allowed`, `app_email_access_allowed`); burası onu her girişte sorar:
yeni hesap (`registration_gate`), parola ve Google ile giriş ile UYAP eklentisinin bağlantı anahtarı (`user_allowed`),
açık oturumların her isteği (`api.auth.routes.resolve_session`). Yöneticiler listede olmasa da girer (kendini kilitleme
yok); askıdaki ya da silinmiş hesap hiçbir modda giremez. Kimlik doğrulama öncesi çalıştığı için nhr_app bağlantısıyla
sorulur; işlevler nhr_runtime'a kapalıdır.

`ALLOW_REGISTRATION=false` (kurulum anahtarı) yeni hesap açmayı her durumda kapatır; mevcut hesapların girişini etkilemez.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import psycopg

from api.config import get_settings

MODES = ("open", "allowlist")
DEFAULT_MODE = "open"
DENIED = ("Bu uygulamaya yalnız yöneticinin erişim listesine eklediği e-posta adresleri girebilir. "
          "Erişim için yöneticinizle görüşün.")


class AccessDenied(Exception):
    """Bu e-posta ya da hesap uygulamaya giremez; `detail` kullanıcıya gösterilir."""

    def __init__(self, detail: str = DENIED, reason: Literal["not_listed", "registration_closed"] = "not_listed") -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason = reason


def _value(row, key: str):
    if row is None:
        return None
    return row.get(key) if isinstance(row, dict) else row[0]


def access_mode(connection: psycopg.Connection) -> str:
    """Yöneticinin seçtiği mod; tablo yoksa (migration 062 öncesi) eski davranış: herkes."""
    try:
        with connection.transaction():  # savepoint: eksik tablo dıştaki transaction'ı bozmasın
            row = connection.execute("SELECT value FROM platform_settings WHERE key = 'access_mode'").fetchone()
    except (psycopg.errors.UndefinedTable, psycopg.errors.InsufficientPrivilege):
        return DEFAULT_MODE
    value = _value(row, "value")
    return value if value in MODES else DEFAULT_MODE


def user_allowed(connection: psycopg.Connection, user_id: UUID) -> bool:
    """Hesap şu an uygulamaya girebilir mi: aktif ve (mod herkes, e-postası listede ya da yönetici).

    İşlev yoksa (migration 062 öncesi) erişim listesi de yoktur: eski davranış, izin verilir.
    """
    try:
        with connection.transaction():
            row = connection.execute("SELECT public.app_user_access_allowed(%s) AS allowed", (user_id,)).fetchone()
    except psycopg.errors.UndefinedFunction:
        return True
    return bool(_value(row, "allowed"))


def registration_gate(connection: psycopg.Connection, email: str) -> None:
    """Yeni hesaba izin verir ya da `AccessDenied` atar; hesabı oluşturan transaction'ın içinde çağrılır."""
    if not get_settings().allow_registration:
        raise AccessDenied("Yeni kullanıcı kaydı kapalı", reason="registration_closed")
    try:
        with connection.transaction():
            row = connection.execute("SELECT public.app_email_access_allowed(%s) AS allowed", (email,)).fetchone()
    except psycopg.errors.UndefinedFunction:
        return
    if not _value(row, "allowed"):
        raise AccessDenied()
