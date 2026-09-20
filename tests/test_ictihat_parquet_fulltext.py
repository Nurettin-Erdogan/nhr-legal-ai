from datetime import date

from ingestion.ictihat_parquet_fulltext import prepare_parquet_fulltext_row


def test_prepare_maps_parquet_columns_and_pending_provenance():
    row = prepare_parquet_fulltext_row(
        {
            "document_id": 123456,
            "esas_no": "2018/14",
            "karar_no": "2018/99",
            "karar_tarihi": "12.03.2018",
            "daire": "9. Hukuk Dairesi",
            "text": "A" * 90,
        },
        shard=0,
    )
    assert row is not None
    assert row.quarantine_code is None
    assert row.external_id == "yargitay:123456"
    assert row.docket_no == "2018/14"
    assert row.decision_no == "2018/99"
    assert row.decision_date == date(2018, 3, 12)
    assert row.court_name == "Yargıtay"
    assert row.metadata["official_verified"] is False
    assert row.metadata["import_type"] == "parquet_fulltext_seed"
    assert row.metadata["dataset"] == "muhammedturan/turk-ictihat-kararlari-fulltext"


def test_prepare_skips_short_or_invalid_ids():
    assert prepare_parquet_fulltext_row({"document_id": -6, "text": "A" * 90}) is None
    assert prepare_parquet_fulltext_row({"document_id": "12", "text": "kisa"}) is None
    assert prepare_parquet_fulltext_row({"document_id": "12", "text": "  \n  "}) is None


def test_prepare_uses_inventory_when_parquet_metadata_missing():
    row = prepare_parquet_fulltext_row(
        {"document_id": "99", "esas_no": "", "karar_no": "", "karar_tarihi": "-", "text": "B" * 90},
        inventory={
            "docket_no": "2010/1",
            "decision_no": "2010/2",
            "decision_date": date(2010, 1, 2),
            "chamber": "11. Hukuk Dairesi",
        },
    )
    assert row is not None
    assert row.docket_no == "2010/1"
    assert row.decision_no == "2010/2"
    assert row.decision_date == date(2010, 1, 2)
    assert row.chamber == "11. Hukuk Dairesi"
