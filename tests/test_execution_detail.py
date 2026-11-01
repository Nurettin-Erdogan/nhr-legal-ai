"""İcra dosyası dökümü: makbuz listesi ve haciz ihbarnamesi cevapları (metinler uydurma örneklerdir, gerçek veri değildir).

Gerçek veride ölçülen (2026-10-09): "89/1 Haciz İhbarnamesi Cevabı" evrakının kendisi yalnız KEP zarfıdır, bankanın yazısı
ekinde durur; banka yazıları koşullu cümlelerle doludur. Bu yüzden cevabın sonucu söylenmez; metinde ne geçtiği gösterilir.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api import execution
from api.main import app
from tests.test_case_document_rag import db, needs_db  # noqa: F401  (fixture)
from tests.test_execution import _index, _world

REPLY_PATH = "2025/123 (İcra Dosyası) / 89/1 Haciz İhbarnamesi Cevabı / 89/1 Haciz İhbarnamesi Cevabı 12/03/2025"
NEGATIVE = (
    "Örnek Bankası A.Ş. Genel Müdürlüğü Sayı: 123 Ankara Banka Alacakları İcra Dairesi'ne İlgi: 10.03.2025 tarihli yazınız. "
    "Borçlunun Bankamız nezdinde herhangi bir hak ve alacağı bulunmadığı tespit edilmiştir. "
    "İİK 89. maddesi gereğince haciz ihbarnamesine itiraz ederiz. Saygılarımızla."
)
POSITIVE = (
    "DENEMEBANK T.A.Ş. Hukuk Müdürlüğü İlgi: 10.03.2025 tarihli haciz ihbarnamesi. "
    "Borçlunun Bankamız nezdindeki hesabında bulunan 1.250,75 TL üzerine bloke konulmuştur. Bilgilerinize sunarız."
)
CONDITIONAL = (
    "Türkiye Deneme Bankası A.Ş. İlgi yazınız incelenmiştir. Borçlunun hesaplarına haciz şerhi işlenmiş olup "
    "bakiye oluşması halinde ayrıca bilgi verilecektir. Saygılarımızla."
)


# --- Veritabanı gerektirmeyenler -----------------------------------------------------------------------------------------


def test_requires_a_session():
    assert TestClient(app).get(f"/api/office/execution/files/{uuid4()}").status_code == 401


def test_receipt_amounts_are_listed_as_written_and_never_added_up():
    text = "Harç 12,50 TL Masraf 1.234,56 TL Toplam 1.247,06 TL tekrar 12,50 TL"

    assert execution.receipt_amounts(text) == ["12,50 TL", "1.234,56 TL", "1.247,06 TL"]
    assert execution.receipt_amounts("tutar yok") == []
    assert execution.receipt_amounts("") == []


@pytest.mark.parametrize(
    "doc_type, path, expected",
    [
        ("Ek", REPLY_PATH, True),
        ("EK", "2025/1 (İcra Dosyası) / 89/2 Haciz İhbarnamesi Cevabı / 89/2 Haciz İhbarnamesi Cevabı 01/02/2025", True),
        ("Ek", "2025/1 (İcra Dosyası) / Takip Talebi / Takip Talebi 01/02/2025", False),  # başka evrakın eki
        ("Ek", "2025/1 (İcra Dosyası) / 89/1 Haciz İhbarnamesi Cevabı", False),  # yolun ucunda ana evrak yok
        ("89/1 Haciz İhbarnamesi Cevabı", REPLY_PATH, False),  # zarfın kendisi ek değildir
        ("Ek", None, False),
    ],
)
def test_a_reply_attachment_is_recognised_from_its_place_in_the_uyap_tree(doc_type, path, expected):
    assert execution.is_reply_attachment(doc_type, path) is expected


def test_the_document_date_is_read_from_the_end_of_the_uyap_path():
    assert execution.path_date(REPLY_PATH) == date(2025, 3, 12)
    assert execution.path_date("… Cevabı 31/02/2025") is None  # olmayan tarih uydurulmaz
    assert execution.path_date("… Cevabı") is None
    assert execution.path_date(None) is None


def test_a_negative_reply_is_quoted_verbatim_and_its_sender_is_read_from_the_letterhead():
    summary = execution.reply_summary(NEGATIVE)

    assert summary["group"] == "negative" and summary["amounts"] == []
    assert summary["quotes"] == ["Borçlunun Bankamız nezdinde herhangi bir hak ve alacağı bulunmadığı tespit edilmiştir."]
    assert summary["quotes"][0] in NEGATIVE  # alıntı kaynaktan aynen alınır
    assert summary["sender"] == "Örnek Bankası A.Ş."


def test_a_reply_that_mentions_an_amount_comes_first_and_the_amount_is_shown_as_written():
    summary = execution.reply_summary(POSITIVE)

    assert summary["group"] == "amount"
    assert summary["amounts"] == ["1.250,75 TL"]
    assert summary["quotes"] == ["Borçlunun Bankamız nezdindeki hesabında bulunan 1.250,75 TL üzerine bloke konulmuştur."]
    assert summary["mentions_block"] is True
    assert summary["sender"] == "DENEMEBANK T.A.Ş."


def test_a_reply_without_a_decisive_phrase_is_left_undecided_instead_of_guessed():
    summary = execution.reply_summary(CONDITIONAL)

    assert summary["group"] == "unclear"
    assert summary["quotes"] == [] and summary["amounts"] == []
    assert summary["sender"] == "Türkiye Deneme Bankası A.Ş."


def test_a_reply_with_both_a_negative_phrase_and_the_word_bloke_is_not_called_negative():
    text = "Borçlunun hesabı bulunmamaktadır. İleride doğacak alacaklar bakımından bloke kaydı işlenmiştir."

    summary = execution.reply_summary(text)

    assert summary["group"] == "block"  # yalnız metinde ne geçtiği söylenir; iki cümle de alıntılanır
    assert summary["mentions_negative"] is True and len(summary["quotes"]) == 2


def test_turkish_capital_letters_and_dotless_i_do_not_hide_the_phrase():
    summary = execution.reply_summary("BORÇLUNUN BANKAMIZDA HESABI BULUNMAMAKTADIR. Bilgilerinize.")

    assert summary["group"] == "negative"
    assert summary["quotes"] == ["BORÇLUNUN BANKAMIZDA HESABI BULUNMAMAKTADIR."]


def test_abbreviations_do_not_cut_the_quoted_sentence_short():
    text = "Giriş cümlesi. Borçlu Örnek Tic. Ltd. Şti. adına Bankamız nezdinde hesap bulunmamaktadır. Son cümle."

    assert execution.reply_summary(text)["quotes"] == [
        "Borçlu Örnek Tic. Ltd. Şti. adına Bankamız nezdinde hesap bulunmamaktadır."
    ]


def test_a_very_long_sentence_is_trimmed_around_the_phrase_and_marked():
    filler = "uzun bir açıklama " * 40
    text = f"{filler}bulunmamaktadır {filler}."

    quote = execution.reply_summary(text)["quotes"][0]

    assert len(quote) <= execution._QUOTE_LIMIT + 2 and quote.startswith("…") and quote.endswith("…")
    assert "bulunmamaktadır" in quote


def test_the_plain_word_banka_is_not_mistaken_for_a_sender_and_code_prefixes_are_dropped():
    assert execution.reply_summary("Ankara Banka Alacakları İcra Dairesi Dosya No: 2025/1")["sender"] is None
    assert execution.reply_summary("DVK Türkiye Deneme Bankası Genel Müdürlüğü")["sender"] == "Türkiye Deneme Bankası"
    assert execution.reply_summary("T.C. DENEME BANKASI A.Ş. Şubesi")["sender"] == "T.C. DENEME BANKASI A.Ş."
    assert execution.reply_summary("XYZ Bank A.Ş. Hukuk Müdürlüğü")["sender"] == "XYZ Bank A.Ş."


def _row(doc_type, *, path=None, day=date(2025, 3, 12), document_id=None):
    return {
        "case_id": UUID(int=1), "case_no": "2025/123", "esas_no": "2025/123", "court": "Ankara  Banka Alacakları İcra Dairesi",
        "document_id": document_id or uuid4(), "doc_type": doc_type, "doc_date": day, "uyap_path": path, "file_name": "x.pdf",
        "storage_path": "sahip/x.pdf",
    }


def test_the_breakdown_lists_every_receipt_and_orders_replies_by_what_their_text_mentions():
    receipt_one, receipt_many, refund = _row("Tahsilat makbuzu"), _row("Masraf Makbuzu"), _row("Reddiyat makbuzu")
    negative, positive, undecided = (_row("Ek", path=REPLY_PATH) for _ in range(3))
    duplicate = _row("Ek", path=REPLY_PATH)  # aynı yazının ikinci kopyası (KEP paketi + PDF)
    unread = _row("Ek", path=REPLY_PATH)
    other_attachment = _row("Ek", path="2025/123 (İcra Dosyası) / Takip Talebi / Takip Talebi 01/02/2025")
    rows = [receipt_one, receipt_many, refund, _row("89/1 Haciz İhbarnamesi Cevabı"), negative, positive, undecided,
            duplicate, unread, other_attachment, _row("Takip Talebi")]
    texts = {
        receipt_one["document_id"]: "Tutarı 100,00 TL (*) 100,00 TL",
        receipt_many["document_id"]: "Posta 45,00 TL Toplam 90,00 TL",
        negative["document_id"]: NEGATIVE, positive["document_id"]: POSITIVE, undecided["document_id"]: CONDITIONAL,
        duplicate["document_id"]: NEGATIVE,
    }

    detail = execution.build_detail(rows, texts)

    assert detail["file_no"] == "2025/123" and detail["court"] == "Ankara Banka Alacakları İcra Dairesi"
    receipts = {item["document"]["id"]: item for item in detail["receipts"]}
    assert receipts[receipt_one["document_id"]]["amount"] == "100,00 TL"
    # Birden çok farklı tutar: hangisinin makbuz tutarı olduğu bilinemez; hepsi yazıldığı gibi listelenir, biri seçilmez.
    assert receipts[receipt_many["document_id"]]["amount"] is None
    assert receipts[receipt_many["document_id"]]["amounts"] == ["45,00 TL", "90,00 TL"]
    assert receipts[refund["document_id"]]["readable"] is False and receipts[refund["document_id"]]["amounts"] == []
    replies = detail["replies"]
    assert (replies["envelopes"], replies["attachments"], replies["unread"]) == (1, 5, 1)
    assert [item["group"] for item in replies["items"]] == ["amount", "unclear", "unclear", "negative"]
    assert replies["groups"] == {"amount": 1, "unclear": 2, "negative": 1}
    merged = replies["items"][-1]
    assert [doc["id"] for doc in merged["documents"]] == [negative["document_id"], duplicate["document_id"]]  # iki kopya tek satır, ikisi de açılabilir
    assert merged["documents"][0] == {"id": negative["document_id"], "file_name": "x.pdf", "storage_path": "sahip/x.pdf"}
    assert [item["readable"] for item in replies["items"]].count(False) == 1
    assert all(item["date"] == date(2025, 3, 12) for item in replies["items"])
    listed = {doc["id"] for item in replies["items"] for doc in item["documents"]}
    assert other_attachment["document_id"] not in listed  # başka evrakın eki cevap sayılmaz


def test_a_file_without_documents_has_empty_sections_and_an_unknown_file_is_none():
    empty = _row("x")
    empty["document_id"] = None

    detail = execution.build_detail([empty], {})

    assert detail["receipts"] == [] and detail["replies"]["items"] == [] and detail["replies"]["groups"] == {}
    assert execution.build_detail([], {}) is None


def test_only_receipts_and_reply_attachments_have_their_text_read():
    receipt, reply, petition = _row("Masraf Makbuzu"), _row("Ek", path=REPLY_PATH), _row("Takip Talebi")
    none = _row("x")
    none["document_id"] = None

    assert execution.detail_text_ids([receipt, reply, petition, none]) == [receipt["document_id"], reply["document_id"]]


# --- Veritabanı: kullanıcı izolasyonu ---------------------------------------------------------------------------------------


def _file(world, owner, court="Ankara 7. Genel İcra Dairesi"):
    case_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_cases (id, owner_id, case_no, esas_no, court, title) VALUES (%s, %s, '2025/9', '2025/9', %s, 'x')",
        (case_id, owner, court),
    )
    return case_id


def _document(world, owner, case_id, doc_type, *, path=None, text=None):
    document_id = uuid4()
    world.become(None)
    world.connection.execute(
        "INSERT INTO office_case_documents (id, owner_id, case_id, file_name, storage_path, source, doc_type, doc_date, uyap_path) "
        "VALUES (%s, %s, %s, 'm.pdf', %s, 'uyap-avukat-eklentisi', %s, '2025-03-12', %s)",
        (document_id, owner, case_id, f"{owner}/{document_id}", doc_type, path),
    )
    if text is not None:
        _index(world, owner, document_id, text)
    return document_id


@needs_db
def test_the_breakdown_is_only_served_to_the_owner_and_only_for_execution_files(db, monkeypatch):  # noqa: F811
    from fastapi import HTTPException

    world = _world(db, monkeypatch)
    mine = _file(world, world.alice)
    receipt = _document(world, world.alice, mine, "Tahsilat makbuzu", text="Tutarı 100,00 TL")
    reply = _document(world, world.alice, mine, "Ek", path=REPLY_PATH, text=POSITIVE)
    _document(world, world.alice, mine, "89/1 Haciz İhbarnamesi Cevabı")
    lawsuit = _file(world, world.alice, court="Ankara 5. Sulh Hukuk Mahkemesi")

    detail = execution.execution_file_detail(mine, world.alice)

    assert [item["document"]["id"] for item in detail["receipts"]] == [receipt]
    assert detail["receipts"][0]["document"]["storage_path"] == f"{world.alice}/{receipt}"
    assert detail["receipts"][0]["amount"] == "100,00 TL"
    assert detail["replies"]["envelopes"] == 1
    assert [[doc["id"] for doc in item["documents"]] for item in detail["replies"]["items"]] == [[reply]]
    assert detail["replies"]["items"][0]["amounts"] == ["1.250,75 TL"]
    for case_id, user in ((mine, world.bob), (lawsuit, world.alice), (uuid4(), world.alice)):
        with pytest.raises(HTTPException) as denied:
            execution.execution_file_detail(case_id, user)
        assert denied.value.status_code == 404  # başkasının dosyası, icra olmayan dava ve olmayan kayıt ayırt edilemez


@needs_db
def test_trashed_documents_are_left_out_and_an_empty_execution_file_still_opens(db, monkeypatch):  # noqa: F811
    world = _world(db, monkeypatch)
    mine = _file(world, world.alice)
    trashed = _document(world, world.alice, mine, "Ek", path=REPLY_PATH, text=NEGATIVE)
    world.become(None)
    world.connection.execute("UPDATE office_case_documents SET deleted_at = now() WHERE id = %s", (trashed,))

    detail = execution.execution_file_detail(mine, world.alice)

    assert detail["receipts"] == [] and detail["replies"]["items"] == [] and detail["replies"]["attachments"] == 0
