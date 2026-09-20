from ingestion.hf_700k import prepare_row


def test_prepare_row_uses_columns_and_pending_provenance():
    row = prepare_row(
        {
            "id": "872093500",
            "source": "ygty1",
            "esasNo": "2006/3064",
            "kararNo": "2006/5078",
            "kararTarihi": "06.06.2006",
            "text": "**(Kapatılan)17. Hukuk Dairesi 2006/3064 E. , 2006/5078 K.**\n**\"İçtihat Metni\"**\nMAHKEMESİ :Kadastro",
        }
    )

    assert row is not None
    assert row.quarantine_code is None
    assert row.external_id == "yargitay:872093500"
    assert row.docket_no == "2006/3064"
    assert row.decision_no == "2006/5078"
    assert row.chamber == "17. Hukuk Dairesi"
    assert row.metadata["provenance"] == "bulk_seed"
    assert row.metadata["official_verified"] is False
    assert "İçtihat Metni" not in row.raw_text
    assert "**" not in row.raw_text


def test_prepare_row_cgk_does_not_use_referred_chamber():
    row = prepare_row(
        {
            "id": "16388500",
            "source": "ygty1",
            "esasNo": "2004/130",
            "kararNo": "2004/206",
            "kararTarihi": "23.11.2004",
            "text": "Ceza Genel Kurulu 2004/8-130 E., 2004/206 K.\nYARGITAY DAİRESİ : 8. Ceza Dairesi\nMetin",
        }
    )

    assert row is not None
    assert row.chamber == "Ceza Genel Kurulu"
    assert row.docket_no == "2004/130"


def test_prepare_row_danistay_chamber():
    row = prepare_row(
        {
            "id": "1146796000",
            "source": "dnsy1",
            "esasNo": "2022/4009",
            "kararNo": "2025/57",
            "kararTarihi": "15.01.2025",
            "text": "Danıştay 6. Daire Başkanlığı 2022/4009 E. , 2025/57 K.\nALTINCI DAİRE\nEsas No : 2022/4009",
        }
    )

    assert row is not None
    assert row.external_id == "danistay:1146796000"
    assert row.chamber == "6. Daire"


def test_prepare_row_quarantines_dash_date():
    row = prepare_row(
        {
            "id": "1",
            "source": "ygty1",
            "esasNo": "2004/1",
            "kararNo": "2004/2",
            "kararTarihi": "-",
            "text": "9. Hukuk Dairesi 2004/1 E. , 2004/2 K.\nMetin gövdesi burada",
        }
    )

    assert row is not None
    assert row.quarantine_code == "missing_date"


def test_prepare_row_quarantines_empty_text():
    row = prepare_row(
        {
            "id": "2",
            "source": "ygty1",
            "esasNo": "2004/1",
            "kararNo": "2004/2",
            "kararTarihi": "01.01.2004",
            "text": "   ",
        }
    )

    assert row is not None
    assert row.quarantine_code == "empty_text"


def test_prepare_row_omits_cluster_fields():
    row = prepare_row(
        {
            "id": "3",
            "source": "ygty1",
            "esasNo": "2019/1",
            "kararNo": "2019/2",
            "kararTarihi": "01.02.2019",
            "text": "9. Hukuk Dairesi 2019/1 E. , 2019/2 K.\nMetin",
            "orig-e5_hdbscan_cluster_id": 99,
        }
    )

    assert row is not None
    assert "orig-e5_hdbscan_cluster_id" not in row.metadata
    assert row.metadata["cluster_ids_omitted"] is True
