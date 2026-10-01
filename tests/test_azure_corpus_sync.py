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


def test_verification_patch_only_adds_missing_verifications():
    remote = {
        "verified_against_gazette": True,
        "official_gazette_verification": {"verified": True, "detail": "RG"},
        "verified_against_mbs": True,
        "mbs_verification": {"verified": True},
        "verify_attempt_count": 9,
        "verify_last_attempt_at": "2026-10-01T00:00:00+00:00",
    }
    local = {"verified_against_gazette": True, "verify_attempt_count": 75}
    patch = sync.verification_patch(local, remote)
    assert patch == {"verified_against_mbs": True, "mbs_verification": {"verified": True}}


def test_verification_patch_never_revokes_or_copies_counters():
    local = {"verified_against_gazette": True, "verified_against_mbs": True}
    remote = {"verified_against_gazette": False, "verified_against_mbs": None,
              "verify_attempt_count": 3}
    assert sync.verification_patch(local, remote) == {}
    assert sync.verification_patch(None, None) == {}


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConn:
    def __init__(self, metadata):
        self.metadata = metadata
        self.writes = []

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("SELECT"):
            return _Result((self.metadata,))
        self.writes.append((sql, params))
        return _Result(None)


def test_upgrade_marks_ready_only_when_both_sides_are_verified():
    source = {"metadata": {"verified_against_mbs": True, "mbs_verification": {"verified": True}},
              "last_verified_at": None}
    conn = _FakeConn({"verified_against_gazette": True})
    assert sync._upgrade_verification(conn, "local", source, dry_run=False) is True
    (_sql, params), = conn.writes
    merged, both, _both, _stamp, local_id = params
    assert merged.obj["verified_against_gazette"] is True
    assert merged.obj["verified_against_mbs"] is True
    assert both is True and local_id == "local"

    half = _FakeConn({})
    assert sync._upgrade_verification(half, "local", source, dry_run=False) is True
    assert half.writes[0][1][1] is False  # only MBS verified -> status unchanged


def test_upgrade_dry_run_writes_nothing_and_noop_when_nothing_new():
    source = {"metadata": {"verified_against_mbs": True}, "last_verified_at": None}
    conn = _FakeConn({})
    assert sync._upgrade_verification(conn, "local", source, dry_run=True) is True
    assert conn.writes == []
    already = _FakeConn({"verified_against_mbs": True})
    assert sync._upgrade_verification(already, "local", source, dry_run=False) is False
    assert already.writes == []


SEED = {"id": "local", "content_hash": "seed-hash", "ingestion_method": "bulk_seed",
        "ingest_status": "pending", "raw_text": "T.C.\nKONYA\nKARAR NO : 1"}


def _official(**over):
    row = {"id": "remote", "content_hash": "official-hash",
           "ingestion_method": "uyap_emsal_public_json_http", "ingest_status": "ready",
           "raw_text": "T.C.\n\nKONYA\n\nKARAR NO : 1", "metadata": {}}
    row.update(over)
    return row


def test_seed_promotion_when_official_text_equals_seed_ignoring_whitespace():
    assert sync.seed_promotion(SEED, _official()) is True


def test_seed_promotion_refuses_when_text_really_differs():
    assert sync.seed_promotion(SEED, _official(raw_text="T.C.\nKONYA\nKARAR NO : 2")) is False


def test_seed_promotion_never_uses_unofficial_or_unready_remote():
    assert sync.seed_promotion(SEED, _official(ingestion_method="bulk_seed")) is False
    assert sync.seed_promotion(SEED, _official(ingest_status="pending")) is False
    assert sync.seed_promotion(SEED, _official(metadata={"third_party": True})) is False


def test_seed_promotion_only_replaces_pending_seed_rows():
    verified = {**SEED, "ingestion_method": "uyap_emsal_public_json_http", "ingest_status": "ready"}
    assert sync.seed_promotion(verified, _official()) is False


def test_merge_reports_promoted_in_dry_run(monkeypatch):
    monkeypatch.setattr(sync, "_existing_source", lambda _c, _r: dict(SEED))
    assert sync.merge_record(object(), _official(), dry_run=True) == "promoted"


def test_remote_sql_keyset_cursor_and_limit():
    after = (datetime(2026, 10, 1, 12, 10, 20, 787357, tzinfo=timezone.utc),
             "114c2b71-00ca-4bd0-a181-7b45e59b24ba")
    sql = sync._remote_sql(None, after=after, limit=1500)
    assert ("(s.updated_at, s.id) > (TIMESTAMPTZ '2026-10-01T12:10:20.787357+00:00', "
            "'114c2b71-00ca-4bd0-a181-7b45e59b24ba'::uuid)") in sql
    assert "ORDER BY s.updated_at, s.id LIMIT 1500" in sql
    assert "LIMIT" not in sync._remote_sql(None)


def test_remote_sql_cursor_rejects_non_uuid_and_naive_time():
    stamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        sync._remote_sql(None, after=(stamp, "x'; DROP TABLE legal_sources;--"))
    with pytest.raises(ValueError, match="timezone"):
        sync._remote_sql(None, after=(datetime(2026, 10, 1),
                                      "114c2b71-00ca-4bd0-a181-7b45e59b24ba"))


def test_lock_allows_only_one_sync_and_releases():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        lock = Path(folder) / "sync.lock"
        assert sync._acquire_lock(lock) is True
        assert sync._acquire_lock(lock) is False
        lock.unlink()
        assert sync._acquire_lock(lock) is True


def test_stale_lock_from_killed_run_is_taken_over():
    import os
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        lock = Path(folder) / "sync.lock"
        lock.write_text("123")
        old = datetime.now().timestamp() - sync.LOCK_STALE_SECONDS - 60
        os.utime(lock, (old, old))
        assert sync._acquire_lock(lock) is True
