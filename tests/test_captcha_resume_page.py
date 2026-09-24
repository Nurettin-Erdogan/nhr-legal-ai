from worker.jobs import _captcha_resume_page


def test_new_window_captcha_starts_from_first_page():
    cursor = {"window_from": "2026-01-01", "window_complete": True}

    assert _captcha_resume_page(cursor) == 1


def test_partial_window_captcha_retains_its_page():
    assert _captcha_resume_page({"page": 31, "window_complete": False}) == 31
    assert _captcha_resume_page({"page": "invalid"}) == 1
