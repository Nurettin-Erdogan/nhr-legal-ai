from worker.reconciliation import coverage_reconciled, listing_is_exhausted, window_may_advance


def test_window_is_complete_only_when_portal_count_matches_fates():
    assert coverage_reconciled(
        expected=3, seen=3, stored=2, duplicate=1, quarantined=0, failed=0
    )
    assert coverage_reconciled(
        expected=0, seen=0, stored=0, duplicate=0, quarantined=0, failed=0
    )
    assert not coverage_reconciled(
        expected=3, seen=2, stored=2, duplicate=0, quarantined=0, failed=0
    )
    assert not coverage_reconciled(
        expected=3, seen=3, stored=1, duplicate=0, quarantined=0, failed=0
    )
    assert not coverage_reconciled(
        expected=2, seen=2, stored=1, duplicate=0, quarantined=0, failed=1
    )
    assert coverage_reconciled(
        expected=2, seen=2, stored=1, duplicate=0, quarantined=1, failed=0
    )
    assert not coverage_reconciled(
        expected=None, seen=0, stored=0, duplicate=0, quarantined=0, failed=0
    )


def test_exhausted_resume_point_may_advance_without_reconcile():
    assert window_may_advance(
        reconciled=True, processed=10, failed=0, already_started=True
    )
    assert window_may_advance(
        reconciled=False, processed=0, failed=0, already_started=True
    )
    assert not window_may_advance(
        reconciled=False, processed=0, failed=0, already_started=False
    )
    assert not window_may_advance(
        reconciled=False, processed=0, failed=1, already_started=True
    )
    assert not window_may_advance(
        reconciled=False, processed=4, failed=0, already_started=True
    )
    assert not window_may_advance(
        reconciled=True, processed=0, failed=0, already_started=True, stopped=True
    )
    assert window_may_advance(
        reconciled=False,
        processed=4,
        failed=0,
        already_started=True,
        listing_exhausted=True,
    )
    assert not listing_is_exhausted(
        expected=15,
        page_number=1,
        page_size=20,
        row_offset=10,
        page_row_count=20,
        processed=10,
        max_records=80,
        stopped=False,
    )
    assert listing_is_exhausted(
        expected=15,
        page_number=1,
        page_size=20,
        row_offset=15,
        page_row_count=15,
        processed=5,
        max_records=80,
        stopped=False,
    )
