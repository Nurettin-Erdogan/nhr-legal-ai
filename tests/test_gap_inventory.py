from scripts.gap_inventory import compare_counts


def test_compare_counts_orders_positive_differences_and_clamps_overcoverage():
    portal = {"yargitay": {"2025": 100, "2026": 20}, "danistay": {"2025": 10, "2026": "captcha"}}
    db = {("yargitay", 2025): 90, ("yargitay", 2026): 25, ("danistay", 2025): 0}

    rows = compare_counts(portal, db, [2025, 2026])

    assert rows[0]["source"] == "yargitay"
    assert rows[0]["count_difference"] == 10
    assert rows[1]["source"] == "danistay"
    assert rows[1]["count_difference"] == 10
    assert rows[2]["count_difference"] == 0
    assert rows[3]["count_difference"] is None
