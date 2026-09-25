from datetime import date

from scripts.backfill_campaign import _adjust_pacing, _ordered_years, _park_partial_cursor, _saved_cursor


def test_priority_years_do_not_drop_historical_sweep():
    years = _ordered_years(date(2020, 1, 1), date(2026, 9, 24), newest_first=False, priority_years=[2026, 2022, 2026, 1999])

    assert years == [2026, 2022, 2020, 2021, 2023, 2024, 2025]


def test_adaptive_pacing_slows_only_rate_limited_request_type():
    common = dict(document_delay=7.5, listing_delay=4.0, base_document_delay=7.5, base_listing_delay=4.0, success_streak=2, status="partial")
    document = _adjust_pacing(**common, error="HTTP 429 (/getDokuman?id=12)")
    listing = _adjust_pacing(**common, error="HTTP 429 (/aramadetaylist)")

    assert document == (9.375, 4.0, 0)
    assert listing == (7.5, 5.0, 0)


def test_adaptive_pacing_recovers_after_three_clean_runs():
    result = _adjust_pacing(
        document_delay=10.0,
        listing_delay=6.0,
        base_document_delay=7.5,
        base_listing_delay=4.0,
        success_streak=2,
        status="success",
        error="",
    )

    assert result == (9.0, 5.4, 0)


def test_adaptive_pacing_does_not_shorten_captcha_wait():
    result = _adjust_pacing(
        document_delay=7.5,
        listing_delay=4.0,
        base_document_delay=7.5,
        base_listing_delay=4.0,
        success_streak=2,
        status="captcha_required",
        error="CAPTCHA",
    )

    assert result == (8.25, 4.4, 0)


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
