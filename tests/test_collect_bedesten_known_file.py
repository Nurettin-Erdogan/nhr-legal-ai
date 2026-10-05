import gzip
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from collect_bedesten import KnownFile  # noqa: E402


def test_known_file_filters_years_and_counts_days(tmp_path):
    path = tmp_path / "known.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("2024-05-01\t11\n2024-05-01\t12\n2024-05-02\t13\n2019-01-01\t99\n2024-05-01\t11\n")
    known = KnownFile(str(path), 2020, 2026)
    assert known.ids == {"11", "12", "13"}
    assert known.day_counts(date(2024, 5, 1), date(2024, 5, 31)) == {date(2024, 5, 1): 2, date(2024, 5, 2): 1}
    known.add(date(2024, 5, 2), "14")
    assert known.day_counts(date(2024, 5, 2), date(2024, 5, 2)) == {date(2024, 5, 2): 2}
