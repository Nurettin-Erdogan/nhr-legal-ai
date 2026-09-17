from worker.reconciliation import coverage_reconciled, window_may_advance


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
