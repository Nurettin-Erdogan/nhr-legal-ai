"""Zamanı gelen e-posta hatırlatmalarını gönderir (arka plan işi).

Hatırlatmanın kanalı "E-posta" ise ve SMTP yapılandırılmışsa, zamanı geldiğinde hesap sahibinin e-posta adresine tek bir ileti
gönderilir; hatırlatma `sent` olur ve `notified_at` yazılır (ikinci kez gönderilmez). SMTP yapılandırılmamışsa bu iş hiçbir şey
yapmaz: hatırlatma `pending` kalır ve uygulama içinde (zil ve bildirim) gösterilir; e-posta gönderilmiş gibi yapılmaz.

Bu iş kullanıcılar arası çalıştığı için yönetici bağlantısını (`nhr_app`) kullanır; yalnız zamanı gelmiş e-posta hatırlatmalarının
başlığını, notunu ve sahibinin e-postasını okur. İleti içeriği ve adres günlüğe yazılmaz.
"""

from __future__ import annotations

import logging

import psycopg

from api import mailer
from api.db import admin_database_connection

logger = logging.getLogger(__name__)

BATCH = 25
# Çok eski hatırlatma (ör. sunucu günlerce kapalı kaldı) sonradan toplu e-posta olarak gönderilmez; uygulama içinde görünür.
MAX_LATE_HOURS = 24

_DUE_SQL = """
SELECT r.id, r.title, r.note, r.remind_at, u.email
FROM office_reminders r
JOIN users u ON u.id = r.owner_id
WHERE r.channel = 'email' AND r.status = 'pending' AND r.notified_at IS NULL
  AND r.remind_at <= now() AND r.remind_at > now() - make_interval(hours => %s)
  AND u.deleted_at IS NULL AND u.status = 'active'
ORDER BY r.remind_at
LIMIT %s
FOR UPDATE OF r SKIP LOCKED
"""


def send_due_reminders() -> int:
    """Zamanı gelen e-posta hatırlatmalarını gönderir; gönderilen sayısını döndürür. SMTP yoksa 0."""
    if not mailer.is_configured():
        return 0
    sent = 0
    try:
        with admin_database_connection() as connection, connection.transaction():
            rows = connection.execute(_DUE_SQL, (MAX_LATE_HOURS, BATCH)).fetchall()
            for row in rows:
                when = row["remind_at"].astimezone().strftime("%d.%m.%Y %H:%M")
                body = f"Hatırlatma: {row['title']}\nZaman: {when}\n"
                if row["note"]:
                    body += f"\nNot: {row['note']}\n"
                body += "\nBu ileti JurisAI hatırlatmanız için otomatik gönderildi."
                try:
                    mailer.send_mail(row["email"], f"JurisAI hatırlatma: {row['title'][:120]}", body)
                except mailer.MailError:
                    continue  # bu tur gönderilemedi: `pending` kalır, sonraki turda yeniden denenir
                connection.execute(
                    "UPDATE office_reminders SET status = 'sent', notified_at = now() WHERE id = %s", (row["id"],)
                )
                sent += 1
    except (psycopg.Error, RuntimeError):
        logger.exception("Hatırlatma e-postaları gönderilemedi")
    return sent
