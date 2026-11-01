"""Girişte kaba kuvvet koruması: sayım denetim kaydından, kilitli istemci parolayı sınayamaz."""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from api.audit import AUTH_LOGIN_FAILED, email_fingerprint
from api.auth import routes
from api.auth.routes import (
    LOGIN_MAX_FAILURES_PER_EMAIL_IP,
    LOGIN_MAX_FAILURES_PER_IP,
    LOGIN_WINDOW_MINUTES,
    _login_throttle,
    login_retry_after_seconds,
)

DATABASE_URL = os.getenv("NHR_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not DATABASE_URL, reason="NHR_TEST_DATABASE_URL gerekir")


def test_below_both_limits_is_allowed():
    assert login_retry_after_seconds(LOGIN_MAX_FAILURES_PER_EMAIL_IP - 1, LOGIN_MAX_FAILURES_PER_IP - 1) is None
    assert login_retry_after_seconds(0, 0) is None


def test_email_and_ip_pair_limit_blocks_with_the_window_as_retry_after():
    assert login_retry_after_seconds(LOGIN_MAX_FAILURES_PER_EMAIL_IP, 0) == LOGIN_WINDOW_MINUTES * 60


def test_single_ip_spraying_many_emails_is_blocked():
    assert login_retry_after_seconds(0, LOGIN_MAX_FAILURES_PER_IP) == LOGIN_WINDOW_MINUTES * 60


def test_count_query_uses_the_partial_index_predicate_and_never_stores_the_email():
    sql = routes._LOGIN_FAILURE_COUNTS
    assert "action = 'auth.login_failed'" in sql  # idx_activity_logs_login_failed_recent ile aynı koşul
    assert "created_at > now()" in sql
    assert "@" not in sql


@pytest.fixture
def connection():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.transaction():
            yield conn
            raise psycopg.Rollback


def _fail(conn, email: str, ip: str, *, minutes_ago: int = 0) -> None:
    conn.execute(
        """
        INSERT INTO activity_logs (id, action, request_id, ip_address, metadata, created_at)
        VALUES (%s, %s, %s, %s::inet, %s::jsonb, now() - make_interval(mins => %s))
        """,
        (uuid4(), AUTH_LOGIN_FAILED, uuid4(), ip,
         f'{{"reason":"invalid_credentials","email_fingerprint":"{email_fingerprint(email)}"}}', minutes_ago),
    )


@requires_db
def test_database_counts_only_recent_failures_for_the_same_email_and_ip(connection):
    email = f"throttle-{uuid4().hex[:8]}@example.com"
    for _ in range(LOGIN_MAX_FAILURES_PER_EMAIL_IP):
        _fail(connection, email, "203.0.113.10")
    assert _login_throttle(connection, email, "203.0.113.10") == LOGIN_WINDOW_MINUTES * 60
    # Aynı e-posta başka bir IP'den: mağdurun hesabı saldırganın IP'siyle kilitlenmez.
    assert _login_throttle(connection, email, "203.0.113.99") is None
    # Başka bir e-posta aynı IP'den: çift sınırı değil, IP toplamı sayılır (henüz eşikte değil).
    assert _login_throttle(connection, f"other-{uuid4().hex[:8]}@example.com", "203.0.113.10") is None


@requires_db
def test_old_failures_outside_the_window_do_not_block(connection):
    email = f"old-{uuid4().hex[:8]}@example.com"
    for _ in range(LOGIN_MAX_FAILURES_PER_EMAIL_IP + 3):
        _fail(connection, email, "203.0.113.20", minutes_ago=LOGIN_WINDOW_MINUTES + 5)
    assert _login_throttle(connection, email, "203.0.113.20") is None


@requires_db
def test_ip_total_blocks_across_different_emails(connection):
    for index in range(LOGIN_MAX_FAILURES_PER_IP):
        _fail(connection, f"spray-{index}-{uuid4().hex[:6]}@example.com", "203.0.113.30")
    assert _login_throttle(connection, "brand-new@example.com", "203.0.113.30") == LOGIN_WINDOW_MINUTES * 60


@requires_db
def test_missing_ip_is_counted_together_not_ignored(connection):
    email = f"noip-{uuid4().hex[:8]}@example.com"
    for _ in range(LOGIN_MAX_FAILURES_PER_EMAIL_IP):
        connection.execute(
            "INSERT INTO activity_logs (id, action, request_id, ip_address, metadata) "
            "VALUES (%s, %s, %s, NULL, %s::jsonb)",
            (uuid4(), AUTH_LOGIN_FAILED, uuid4(),
             f'{{"email_fingerprint":"{email_fingerprint(email)}"}}'),
        )
    assert _login_throttle(connection, email, None) == LOGIN_WINDOW_MINUTES * 60
