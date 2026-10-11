"""Tebliğ kayıtları: e-tebliğ mazbatasından okunan damgalar ve "yapılmış sayılma" günü (metinler uydurma örneklerdir).

Kalıp gerçek mazbatalardan alındı (2026-10-09): iki tarih yazımı vardır ("03/09/2026 10:15" ve "2026-09-03 10:15:07").
Hiçbir süre başlatılmaz; hesap kuralı korpustaki resmî maddede doğrulanamazsa hesap yapılmaz.
"""

from __future__ import annotations

import contextlib
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api import service_records
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)
from tests.test_execution import _index

SLASHED = (
    "T.C. ANKARA 1. ASLİYE HUKUK MAHKEMESİ E-TEBLİGAT Vekili : BU ZARFTA Gerekçeli Karar - Karar No: 2026/15 - 01/09/2026 VARDIR. "
    "Tebliğ Evrakı, Örnek No: 12 Tarih Açıklama "
    "03/09/2026 10:14 Muhatap hesabına teslim edilmek üzere UETS tarafından teslim alındı. "
    "03/09/2026 10:15 Tebligat alıcı için ayrılmış tebligat alanına (hesabına) başarılı bir şekilde konuldu. "
    "04/09/2026 09:02 Tebligat, alıcısı tarafından açıldı. "
    "2026-09-08 Tebligat, alıcının hesabına iletilmesine müteakip mevzuat gereği belirlenen süre sonunda otomatik olarak okundu sayıldı."
)
ISO = (
    "TEBLİĞ MAZBATASI Dosya No : 2025/900001 E-TEBLİGAT TARİH AÇIKLAMA "
    "2026-02-27 16:40:05 Muhatap hesabına teslim edilmek üzere UETS tarafından teslim alındı. "
    "2026-02-27 16:40:09 Tebligat alıcı için ayrılmış tebligat alanına (hesabına) başarılı bir şekilde konuldu. "
    "2026-03-04 Tebligat, alıcının hesabına iletilmesine müteakip mevzuat gereği belirlenen süre sonunda otomatik olarak okundu sayıldı."
)
PAPER = "TEBLİĞ MAZBATASI T.C Örnek No: Dosya No : 2025/5 muhatap ..... adreste bulunmadığından 9- tebliğ imkansızlığı ...."
RULE = {"reference": "TEBLİGAT KANUNU (7201) m. 7", "source_url": "https://example.test/7201/7", "law_no": "7201", "article_no": "7"}


# --- Veritabanı gerektirmeyenler -----------------------------------------------------------------------------------------


def test_requires_a_session():
    assert TestClient(app).get(f"/api/office/cases/{uuid4()}/service-records").status_code == 401


def test_event_lines_are_read_with_their_stamps_and_document_dates_are_not_mistaken_for_events():
    events = service_records.parse_service_events(SLASHED)

    assert [(event["kind"], event["at"]) for event in events] == [
        ("received", "2026-09-03T10:14:00"),
        ("delivered", "2026-09-03T10:15:00"),
        ("opened", "2026-09-04T09:02:00"),
        ("deemed", "2026-09-08"),
    ]  # zarftaki evrak tarihi (01/09/2026) olay değildir
    assert events[1]["text"] == "Tebligat alıcı için ayrılmış tebligat alanına (hesabına) başarılı bir şekilde konuldu."
    assert events[1]["text"] in SLASHED  # satır mazbatadan aynen alınır


def test_both_stamp_notations_are_understood():
    events = service_records.parse_service_events(ISO)

    assert [(event["kind"], event["at"]) for event in events] == [
        ("received", "2026-02-27T16:40:05"), ("delivered", "2026-02-27T16:40:09"), ("deemed", "2026-03-04"),
    ]


@pytest.mark.parametrize("text", ["", PAPER, "31/02/2026 10:00 Tebligat alıcı için ayrılmış tebligat alanına (hesabına) başarılı bir şekilde konuldu."])
def test_a_scanned_paper_record_or_an_impossible_date_yields_no_event(text):
    assert service_records.parse_service_events(text) == []


def test_capital_letters_do_not_hide_an_event_line():
    text = "03.09.2026 10:15 TEBLİGAT ALICI İÇİN AYRILMIŞ TEBLİGAT ALANINA (HESABINA) BAŞARILI BİR ŞEKİLDE KONULDU."

    assert [event["kind"] for event in service_records.parse_service_events(text)] == ["delivered"]


def test_the_envelope_content_is_quoted_as_written():
    assert service_records.served_documents(SLASHED) == "Gerekçeli Karar - Karar No: 2026/15 - 01/09/2026"
    assert service_records.served_documents(ISO) is None


def test_the_deemed_day_is_the_fifth_day_after_delivery_and_is_compared_with_what_the_record_says():
    summary = service_records.summarize_record(SLASHED, rule_verified=True)

    assert summary["delivered_on"] == date(2026, 9, 3)
    assert summary["computed_deemed_on"] == date(2026, 9, 8)  # 3 Eylül'ü izleyen beşinci gün
    assert summary["stated_deemed_on"] == date(2026, 9, 8)
    assert summary["agrees"] is True
    assert [event["label"] for event in summary["events"]][1] == "Muhatabın hesabına ulaştı"


def test_a_month_boundary_and_a_leap_day_are_counted_on_the_calendar():
    summary = service_records.summarize_record(ISO, rule_verified=True)  # 27 Şubat 2026 + 5 = 4 Mart 2026

    assert (summary["computed_deemed_on"], summary["agrees"]) == (date(2026, 3, 4), True)
    leap = ISO.replace("2026-02-27", "2028-02-27").replace("2026-03-04", "2028-03-03")
    assert service_records.summarize_record(leap, rule_verified=True)["computed_deemed_on"] == date(2028, 3, 3)


def test_a_record_that_states_another_day_is_flagged_instead_of_silently_corrected():
    summary = service_records.summarize_record(SLASHED.replace("2026-09-08", "2026-09-09"), rule_verified=True)

    assert summary["stated_deemed_on"] == date(2026, 9, 9) and summary["computed_deemed_on"] == date(2026, 9, 8)
    assert summary["agrees"] is False


def test_without_a_verified_rule_nothing_is_computed_but_the_record_is_still_read():
    summary = service_records.summarize_record(SLASHED, rule_verified=False)

    assert summary["computed_deemed_on"] is None and summary["agrees"] is None
    assert summary["delivered_on"] == date(2026, 9, 3) and summary["stated_deemed_on"] == date(2026, 9, 8)


def test_a_record_without_a_delivery_line_has_no_computed_day():
    only_received = "03/09/2026 10:14 Muhatap hesabına teslim edilmek üzere UETS tarafından teslim alındı."

    summary = service_records.summarize_record(only_received, rule_verified=True)

    assert summary["electronic"] is True and summary["delivered_on"] is None and summary["computed_deemed_on"] is None


def _row(doc_type, document_id=None, day=date(2026, 9, 3)):
    return {"case_id": UUID(int=1), "document_id": document_id or uuid4(), "doc_type": doc_type, "doc_date": day,
            "file_name": "m.pdf", "storage_path": "sahip/m.pdf"}


def test_only_service_documents_are_read_and_unreadable_ones_are_counted_not_guessed():
    electronic, older, paper, petition = _row("Kapalı E-Tebliğ Mazbatası"), _row("Kapalı E-Tebliğ Mazbatası"), _row("Tebliğ Mazbatası"), _row("Takip Talebi")
    texts = {electronic["document_id"]: SLASHED, older["document_id"]: ISO, paper["document_id"]: PAPER, petition["document_id"]: SLASHED}

    result = service_records.build_service_records([older, petition, paper, electronic], texts, rule=RULE)

    assert [record["document"]["id"] for record in result["records"]] == [electronic["document_id"], older["document_id"]]  # en yeni tebliğ önce
    assert result["unreadable"] == 1  # kâğıt mazbata; dilekçe tebliğ evrakı değildir, hiç sayılmaz
    assert result["rule"]["sentence"] == service_records.E_SERVICE_RULE_SENTENCE and result["rule"]["days"] == 5
    assert result["rule"]["reference"] == RULE["reference"]
    assert result["records"][0]["served"] == "Gerekçeli Karar - Karar No: 2026/15 - 01/09/2026"


def test_a_case_without_documents_is_empty_and_an_unknown_case_is_none():
    empty = _row("x")
    empty["document_id"] = None

    assert service_records.build_service_records([empty], {}, rule=None) == {"case_id": UUID(int=1), "records": [], "unreadable": 0, "rule": None}
    assert service_records.build_service_records([], {}, rule=RULE) is None


ARTICLE_TEXT = (
    "Uçak, telgraf ve diğer vasıtalarla tebligat ve ücretleri: Madde 7 – Tebligat uçakla yapılabilir. "
    "Elektronik tebligat: Madde 7/a - (Ek : 11/1/2011-6099/2 md.) Aşağıda belirtilen gerçek ve tüzel kişilere tebligatın elektronik "
    "yolla yapılması zorunludur. Elektronik yolla tebligat, muhatabın elektronik adresine ulaştığı tarihi izleyen beşinci günün "
    "sonunda yapılmış sayılır."
)


class _Corpus:
    def __init__(self, row):
        self.row = row
        self.asked = []

    def execute(self, sql, params):
        self.asked.append(params)
        return self

    def fetchone(self):
        return self.row


def _corpus(monkeypatch, row):
    corpus = _Corpus(row)

    @contextlib.contextmanager
    def connection():
        yield corpus

    monkeypatch.setattr(service_records, "database_connection", connection)
    return corpus


def test_the_rule_is_only_trusted_when_the_verified_article_still_carries_the_sentence(monkeypatch):
    row = {"id": UUID(int=7), "source_url": "https://example.test/7201", "law_name": "TEBLİGAT  KANUNU", "law_no": "7201",
           "article_no": "7", "article_title": "Uçak, telgraf", "content": ARTICLE_TEXT}
    corpus = _corpus(monkeypatch, row)

    rule = service_records.verified_e_service_rule()

    assert corpus.asked == [{"law_no": "7201", "article_no": "7"}]
    # Kayıt m. 7 diye durur ama cümle "Madde 7/a" başlığının altındadır: atıf metindeki başlıktan okunur.
    assert rule["reference"] == "TEBLİGAT KANUNU (7201) m. 7/a" and rule["article_no"] == "7/a"
    assert rule["source_url"] == "https://example.test/7201" and rule["verification"] == "official"

    _corpus(monkeypatch, {**row, "content": "Madde 7 – Tebligat uçakla yapılabilir."})  # madde değişmiş: cümle yok
    assert service_records.verified_e_service_rule() is None
    _corpus(monkeypatch, None)  # korpusta doğrulanmış kayıt yok
    assert service_records.verified_e_service_rule() is None


def test_the_article_label_comes_from_the_nearest_heading_before_the_sentence():
    part = service_records.E_SERVICE_RULE.expect[0]

    assert service_records.article_label_for(ARTICLE_TEXT, part, "7") == "7/a"
    assert service_records.article_label_for("Başlıksız metin. " + part, part, "7") == "7"  # başlık yoksa kaydın numarası
    assert service_records.article_label_for("Madde 9 – başka metin", part, "7") == "7"  # cümle yoksa kaydın numarası


def test_the_rule_sentence_shown_to_the_user_contains_the_words_checked_against_the_corpus():
    assert service_records.E_SERVICE_RULE.expect[0] in service_records.E_SERVICE_RULE_SENTENCE


# --- Veritabanı: kullanıcı izolasyonu ---------------------------------------------------------------------------------------


def _world(db, monkeypatch, rule=RULE):  # noqa: F811
    @contextlib.contextmanager
    def as_user(user_id: str):
        db.become(UUID(user_id))
        yield db.connection

    monkeypatch.setattr(service_records, "authenticated_database_connection", as_user)
    monkeypatch.setattr(service_records, "verified_e_service_rule", lambda: rule)
    return db


def _case(world, owner, court="Ankara 1. Asliye Hukuk Mahkemesi"):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, '2026/15', '2026/15', %s, 'x')",
        (case_id, owner, court),
    )
    return case_id


def _document(world, owner, case_id, doc_type, text=None):
    document_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source, doc_type, doc_date) "
        "VALUES (%s, %s, %s, 'm.pdf', %s, 'uyap-avukat-eklentisi', %s, '2026-09-03')",
        (document_id, owner, case_id, f"{owner}/{document_id}", doc_type),
    )
    if text is not None:
        _index(world, owner, document_id, text)
    return document_id


@needs_db
def test_service_records_are_served_only_to_the_owner_of_the_case(db, monkeypatch):  # noqa: F811
    from fastapi import HTTPException

    world = _world(db, monkeypatch)
    mine = _case(world, world.alice)  # icra dosyası olmak şart değil: süre her davada sayılır
    record = _document(world, world.alice, mine, "Kapalı E-Tebliğ Mazbatası", SLASHED)
    _document(world, world.alice, mine, "Tebliğ Mazbatası", PAPER)

    result = service_records.case_service_records(mine, world.alice)

    assert [item["document"]["id"] for item in result["records"]] == [record]
    assert result["records"][0]["computed_deemed_on"] == date(2026, 9, 8) and result["unreadable"] == 1
    assert result["records"][0]["document"]["storage_path"] == f"{world.alice}/{record}"
    for case_id, user in ((mine, world.bob), (uuid4(), world.alice)):
        with pytest.raises(HTTPException) as denied:
            service_records.case_service_records(case_id, user)
        assert denied.value.status_code == 404  # başkasının davası ile olmayan dava ayırt edilemez


@needs_db
def test_trashed_records_are_left_out_and_an_unverified_rule_computes_nothing(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch, rule=None)
    mine = _case(world, world.alice)
    kept = _document(world, world.alice, mine, "Kapalı E-Tebliğ Mazbatası", ISO)
    trashed = _document(world, world.alice, mine, "Kapalı E-Tebliğ Mazbatası", SLASHED)
    world.become(None)
    world.connection.execute("UPDATE office_case_documents SET deleted_at = now() WHERE id = %s", (trashed,))

    result = service_records.case_service_records(mine, world.alice)

    assert [item["document"]["id"] for item in result["records"]] == [kept]
    assert result["rule"] is None and result["records"][0]["computed_deemed_on"] is None
    assert result["records"][0]["stated_deemed_on"] == date(2026, 3, 4)  # mazbatanın kendi satırı yine okunur
