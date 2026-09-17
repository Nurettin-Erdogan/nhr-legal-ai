from datetime import datetime, timezone

import pytest

from scripts import sync_azure_corpus as sync


def test_remote_export_only_reads_public_corpus_and_filters_watermark():
    sql = sync._remote_sql("2026-09-17T06:00:00+00:00")
    assert "FROM legal_sources s" in sql
    assert "FROM legal_chunks" in sql
    assert "FROM court_decision_details" in sql
    assert "FROM legislation_details" in sql
    assert "s.deleted_at IS NULL" in sql
    assert "s.updated_at >= TIMESTAMPTZ '2026-09-17T06:00:00+00:00'" in sql
    assert "FROM users" not in sql
    assert "FROM documents" not in sql


def test_watermark_overlaps_by_one_minute(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"last_updated_at":"2026-09-17T06:00:00+00:00"}')
    assert datetime.fromisoformat(sync._load_since(path, full=False)) == datetime(
        2026, 9, 17, 5, 59, tzinfo=timezone.utc
    )
    assert sync._load_since(path, full=True) is None


def test_invalid_watermark_timezone_is_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"last_updated_at":"2026-09-17T06:00:00"}')
    with pytest.raises(ValueError, match="timezone"):
        sync._load_since(path, full=False)


def test_dry_run_does_not_write_and_reports_conflict(monkeypatch):
    monkeypatch.setattr(sync, "_existing_source", lambda _conn, _row: {
        "id": "local-id", "content_hash": "local-hash"
    })
    payload = {"id": "remote-id", "content_hash": "remote-hash"}
    assert sync.merge_record(object(), payload, dry_run=True) == "conflict"


def test_dry_run_identical_source_is_idempotent(monkeypatch):
    monkeypatch.setattr(sync, "_existing_source", lambda _conn, _row: {
        "id": "local-id", "content_hash": "same-hash"
    })
    payload = {"id": "remote-id", "content_hash": "same-hash"}
    assert sync.merge_record(object(), payload, dry_run=True) == "same"
