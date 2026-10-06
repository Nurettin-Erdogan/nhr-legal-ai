"""E-posta gönderimi (SMTP). Yapılandırılmamışsa gönderim yapılmaz ve çağıran bunu açıkça öğrenir.

Ortam değişkenleri: `SMTP_HOST`, `SMTP_PORT` (varsayılan 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_STARTTLS`
(varsayılan açık; 465 portunda SSL kullanılır). Parola günlüğe yazılmaz; e-posta içeriği ve alıcı adresi de günlüğe yazılmaz.

Yerel kurulumda SMTP çoğunlukla yoktur: o zaman `is_configured()` False döner, arayüz "e-posta bu kurulumda gönderilemiyor" der
ve hiçbir şey gönderilmiş gibi yapılmaz.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    user: str
    password: str
    sender: str
    starttls: bool

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


def mail_settings() -> MailSettings:
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    return MailSettings(
        host=os.getenv("SMTP_HOST", "").strip(),
        port=port,
        user=os.getenv("SMTP_USER", "").strip(),
        password=os.getenv("SMTP_PASSWORD", ""),
        sender=os.getenv("SMTP_FROM", "").strip(),
        starttls=os.getenv("SMTP_STARTTLS", "true").strip().lower() not in {"0", "false", "no"},
    )


def is_configured() -> bool:
    return mail_settings().configured


class MailError(RuntimeError):
    """Gönderim başarısız (ayrıntı günlüğe yazılır, kullanıcıya genel mesaj gösterilir)."""


def send_mail(to: str, subject: str, body: str) -> None:
    """Düz metin e-posta gönderir. Yapılandırma yoksa ya da gönderim başarısızsa `MailError` atar."""
    settings = mail_settings()
    if not settings.configured:
        raise MailError("E-posta gönderimi yapılandırılmadı")
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        if settings.port == 465:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=20, context=ssl.create_default_context()) as client:
                if settings.user:
                    client.login(settings.user, settings.password)
                client.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=20) as client:
                if settings.starttls:
                    client.starttls(context=ssl.create_default_context())
                if settings.user:
                    client.login(settings.user, settings.password)
                client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("E-posta gönderilemedi: %s", type(exc).__name__)
        raise MailError("E-posta gönderilemedi") from exc
