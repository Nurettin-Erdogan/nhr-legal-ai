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


# -- birim (daire) düzeyinde tarama -----------------------------------------------------------
import collect_bedesten  # noqa: E402
from ingestion.bedesten_emsal import BedestenItem, BedestenPage  # noqa: E402


class _FakePortal:
    """Birim süzgeci olan sahte Bedesten: kayıtlar (id, birim, tarih)."""

    min_interval = 4.5

    def __init__(self, records):
        self.records = records
        self.search_calls = 0

    def search(self, kind, start, end, *, page=1, page_size=100, chamber=None):
        self.search_calls += 1
        rows = [r for r in self.records if start <= r[2] <= end and (chamber is None or r[1] == chamber)]
        rows.sort(key=lambda r: r[2], reverse=True)
        chunk = rows[(page - 1) * page_size: page * page_size]
        return BedestenPage(total=len(rows), items=[BedestenItem(i, c, "", "", d) for i, c, d in chunk])

    def content_html(self, document_id):
        return "<p>x</p>"


class _FakeConnection:
    def execute(self, *_args, **_kwargs):
        class _Rows:
            def fetchall(self):
                return []
        return _Rows()


def test_chamber_scan_fetches_only_the_gap_with_far_fewer_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_bedesten, "STATE_DIR", tmp_path)
    records = []
    for day in range(1, 29):  # 2015-10: 3 birim, her gün 120 karar
        for chamber in ("1. Hukuk Dairesi", "2. Hukuk Dairesi", "3. Ceza Dairesi"):
            for n in range(40):
                records.append((f"{chamber[:1]}-{day}-{n}", chamber, date(2015, 10, day)))
    missing = {records[10][0], records[700][0], records[1000][0]}
    known_path = tmp_path / "known.tsv"
    known_path.write_text(
        "".join(f"{d.isoformat()}\t{i}\t{c}\n" for i, c, d in records if i not in missing), encoding="utf-8"
    )
    saved: list[str] = []
    monkeypatch.setattr(collect_bedesten, "decision_from_bedesten", lambda kind, item, html: item)
    monkeypatch.setattr(collect_bedesten, "upsert_decision", lambda connection, item: saved.append(item.document_id))
    portal = _FakePortal(records)
    collector = collect_bedesten.Collector(
        "yargitay", portal, _FakeConnection(), KnownFile(str(known_path), 2015, 2015), by_chamber=True
    )

    collector.collect_month(2015, 10)

    assert set(saved) == missing
    assert portal.search_calls < 40  # gün gün tarama 28 gün x 2 sayfa + toplamlar ister
    assert collector.state["months"]["2015-10"]


def test_chamber_scan_falls_back_when_a_chamber_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_bedesten, "STATE_DIR", tmp_path)
    records = [("a", "1. Hukuk Dairesi", date(2015, 10, 5)), ("b", "Yeni Daire", date(2015, 10, 5))]
    known_path = tmp_path / "known.tsv"
    known_path.write_text("2015-10-05\ta\t1. Hukuk Dairesi\n", encoding="utf-8")
    saved: list[str] = []
    monkeypatch.setattr(collect_bedesten, "decision_from_bedesten", lambda kind, item, html: item)
    monkeypatch.setattr(collect_bedesten, "upsert_decision", lambda connection, item: saved.append(item.document_id))
    collector = collect_bedesten.Collector(
        "yargitay", _FakePortal(records), _FakeConnection(), KnownFile(str(known_path), 2015, 2015), by_chamber=True
    )

    collector.collect_month(2015, 10)

    assert saved == ["b"]  # bilinmeyen birimdeki karar gün taramasına düşüp yine bulundu


def test_noisy_chamber_labels_fall_back_to_day_scan(tmp_path, monkeypatch):
    """Seed'lerde kararlar başka daire adıyla kayıtlıysa birim sayıları tutmaz; ay gün gün taranıp eksik yine bulunur."""
    monkeypatch.setattr(collect_bedesten, "STATE_DIR", tmp_path)
    records = []
    for day in range(1, 29):
        for n in range(30):
            records.append((f"x-{day}-{n}", "1. Hukuk Dairesi" if n % 2 else "2. Hukuk Dairesi", date(2015, 10, day)))
    missing = {records[100][0]}
    # Bizdeki kayıtların yarısı yanlış daire adıyla: portal toplamı ile bizim daire sayımız hiç tutmaz.
    lines = []
    for i, c, d in records:
        if i in missing:
            continue
        label = "Genel Kurul" if hash(i) % 2 else c
        lines.append(f"{d.isoformat()}\t{i}\t{label}\n")
    known_path = tmp_path / "known.tsv"
    known_path.write_text("".join(lines), encoding="utf-8")
    saved: list[str] = []
    monkeypatch.setattr(collect_bedesten, "decision_from_bedesten", lambda kind, item, html: item)
    monkeypatch.setattr(collect_bedesten, "upsert_decision", lambda connection, item: saved.append(item.document_id))
    collector = collect_bedesten.Collector(
        "yargitay", _FakePortal(records), _FakeConnection(), KnownFile(str(known_path), 2015, 2015), by_chamber=True
    )

    collector.collect_month(2015, 10)

    assert set(saved) == missing
