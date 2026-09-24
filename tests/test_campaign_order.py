from datetime import date

from scripts.backfill_campaign import _park_partial_cursor, _saved_cursor


def test_park_and_restore_partial_year_cursor():
    cursor = {
        "window_from": "2025-01-01",
        "window_to": "2025-12-31",
        "window_complete": False,
        "chamber": "",
        "page": 755,
        "row_offset": 4,
    }
    parked = {}

    assert _park_partial_cursor(parked, "", cursor, date(1982, 1, 1), date(2026, 9, 24)) == "|2025"
    assert _saved_cursor(parked, "", date(2025, 1, 1), date(2025, 12, 31)) == cursor
    assert _saved_cursor(parked, "", date(2024, 1, 1), date(2024, 12, 31)) is None


def test_only_matching_incomplete_chamber_cursor_is_parked():
    parked = {}
    cursor = {"window_from": "2021-01-01", "window_to": "2021-12-31", "window_complete": False, "chamber": "Ceza Genel Kurulu"}

    assert _park_partial_cursor(parked, "Hukuk Genel Kurulu", cursor, date(2000, 1, 1), date(2026, 9, 24)) is None
    assert _park_partial_cursor(parked, "Ceza Genel Kurulu", {**cursor, "window_complete": True}, date(2000, 1, 1), date(2026, 9, 24)) is None
    assert parked == {}
