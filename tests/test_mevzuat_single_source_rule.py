"""Mevzuat doğrulama kuralı (kullanıcı kararı 2026-10-15): bir resmî kaynakla eşleşen yeterli; ikisiyle de
eşleşmeyen, birkaç denemeden sonra korpustan çıkarılır."""

from ingestion.mevzuat import official_verify as ov


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self


LAW = {"legislation_type": "communique", "law_no": "1234", "official_gazette_date": None, "official_gazette_no": "30000"}


def _trashed(conn: _Conn) -> bool:
    return any(sql is ov._TRASH_SQL for sql, _ in conn.calls)


def test_apply_marks_ready_when_either_source_matches():
    assert "OR (ls.metadata || %s)->>'verified_against_mbs' = 'true'" in ov._APPLY_SQL
    conn = _Conn()
    law = {**LAW, "metadata": {"verify_attempt_count": 10}}
    ov.apply_law_verification(conn, law, flags={"verified_against_gazette": True, "verified_against_mbs": False}, results={})
    assert not _trashed(conn)


def test_unmatched_law_is_trashed_after_enough_attempts():
    conn = _Conn()
    law = {**LAW, "metadata": {"verify_attempt_count": ov.TRASH_AFTER_ATTEMPTS - 1}}
    ov.apply_law_verification(conn, law, flags={"verified_against_gazette": False, "verified_against_mbs": False}, results={})
    assert _trashed(conn)


def test_unmatched_law_gets_more_attempts_first():
    conn = _Conn()
    law = {**LAW, "metadata": {"verify_attempt_count": 0}}
    ov.apply_law_verification(conn, law, flags={"verified_against_gazette": False, "verified_against_mbs": False}, results={})
    assert not _trashed(conn)


def test_pending_query_skips_single_source_verified():
    sql = ov._PENDING_LAWS_SQL
    assert "AND ls.metadata->>'verified_against_gazette' IS DISTINCT FROM 'true'\n      AND ls.metadata->>'verified_against_mbs' IS DISTINCT FROM 'true'" in sql
