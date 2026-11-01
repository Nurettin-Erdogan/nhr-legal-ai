"""Zamanı gelen e-posta hatırlatmaları: yalnız SMTP kuruluysa, bir kez ve yalnız sahibine gönderilir."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from api import mailer, reminder_mailer
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)


@pytest.fixture
def world(db, monkeypatch):  # noqa: F811
    @contextlib.contextmanager
    def admin():
        db.become(None)
        db.connection.execute("SELECT set_config('app.user_id', '', true)")
        yield db.connection

    monkeypatch.setattr(reminder_mailer, "admin_database_connection", admin)
    db.become(None)
    db.connection.execute("UPDATE users SET email = 'alice@example.com' WHERE id = %s", (db.alice,))
    db.connection.execute("UPDATE users SET email = 'bob@example.com' WHERE id = %s", (db.bob,))
    return db


def _reminder(world, owner, *, channel="email", minutes_ago=5, status="pending", title="Müvekkili ara"):
    reminder_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_reminders (id, owner_id, title, note, remind_at, channel, status) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (reminder_id, owner, title, "dosya notu", datetime.now(timezone.utc) - timedelta(minutes=minutes_ago), channel, status),
    )
    return reminder_id


def _state(world, reminder_id):
    world.become(None)
    return world.connection.execute("SELECT status, notified_at FROM office_reminders WHERE id = %s", (reminder_id,)).fetchone()


@needs_db
def test_nothing_is_sent_or_marked_when_mail_is_not_configured(world, monkeypatch):
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    reminder = _reminder(world, world.alice)
    assert reminder_mailer.send_due_reminders() == 0
    state = _state(world, reminder)
    assert state["status"] == "pending" and state["notified_at"] is None  # uygulama içinde gösterilmeye devam eder


@needs_db
def test_a_due_email_reminder_is_sent_once_to_its_owner_only(world, monkeypatch):
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, body: sent.append((to, subject, body)))
    due = _reminder(world, world.alice)
    in_app = _reminder(world, world.alice, channel="in_app")
    future = _reminder(world, world.bob, minutes_ago=-60)
    done = _reminder(world, world.bob, status="done")
    stale = _reminder(world, world.bob, minutes_ago=60 * 48)  # iki gün önce: toplu gecikmiş e-posta gönderilmez

    assert reminder_mailer.send_due_reminders() == 1
    assert [(to, "Müvekkili ara" in subject, "dosya notu" in body) for to, subject, body in sent] == [("alice@example.com", True, True)]
    assert _state(world, due)["status"] == "sent" and _state(world, due)["notified_at"] is not None
    for untouched in (in_app, future, done, stale):
        assert _state(world, untouched)["notified_at"] is None
    assert reminder_mailer.send_due_reminders() == 0 and len(sent) == 1  # ikinci turda yeniden gönderilmez


@needs_db
def test_a_failed_delivery_leaves_the_reminder_pending_for_the_next_round(world, monkeypatch):
    def fail(to, subject, body):
        raise mailer.MailError("sunucu yok")

    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_mail", fail)
    reminder = _reminder(world, world.alice)
    assert reminder_mailer.send_due_reminders() == 0
    assert _state(world, reminder)["status"] == "pending" and _state(world, reminder)["notified_at"] is None
