"""Güncellik notu yalnız saklı doğrulama tarihlerinden kurulur; model yazmaz (ağ/DB gerektirmez).

Ölçüldü (2026-10-30): "30 Ekim 2026 itibarıyla 4857 m. 18 ve 20'yi resmî kaynaklardan kontrol et; ulaşamıyorsan hangi tarihe kadar
doğrulayabildiğini açıkça belirt" sorusu iki maddeyi doğru özetledi ama tarih hakkında tek söz söylemedi; metinler 27 Ekim'de
mevzuat.gov.tr ile karşılaştırılmıştı.
"""

from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from api.ai import currency_note, pipeline
from api.ai.verification import VerifiedAnswer
from tests.factories import court_decision_context, legislation_context

QUESTION = ("30 Ekim 2026 tarihi itibarıyla 4857 sayılı İş Kanunu'nun 18 ve 20. maddelerinin yürürlükteki hükümlerini resmî "
            "kaynaklardan kontrol et. Güncel metinlere ulaşamıyorsan hangi tarihe kadar doğrulama yapabildiğini açıkça belirt.")
TODAY = date(2026, 10, 30)
VERIFIED = datetime(2026, 10, 27, 17, 2, tzinfo=timezone.utc)


def _articles():
    m18 = replace(legislation_context(), source_id=uuid4(), chunk_id=uuid4(), law_no="4857", article_no="18")
    m20 = replace(legislation_context(), source_id=uuid4(), chunk_id=uuid4(), law_no="4857", article_no="20")
    return m18, m20


def _records(*contexts, verified=VERIFIED, mbs=True, gazette=False):
    return {str(c.source_id): {"last_verified_at": verified, "mbs": mbs, "gazette": gazette} for c in contexts}


def test_the_question_of_the_screenshot_gets_the_date_and_the_unverified_gap():
    m18, m20 = _articles()
    note = currency_note.verification_note(QUESTION, None, [m18, m20], _records(m18, m20), TODAY)
    assert note.startswith("Doğrulama bilgisi:")
    assert "4857 sayılı Kanun m. 18, m. 20" in note
    assert "Mevzuat Bilgi Sistemi (mevzuat.gov.tr)" in note
    assert "en son 27 Ekim 2026 tarihinde" in note
    assert "27 Ekim 2026 sonrasında yapılmış bir değişiklik bu karşılaştırmaya yansımamış olabilir" in note
    assert "30 Ekim 2026 itibarıyla" in note


def test_a_text_checked_on_the_asked_day_carries_no_gap_sentence():
    m18, _ = _articles()
    today = datetime(2026, 10, 30, 8, tzinfo=timezone.utc)
    note = currency_note.verification_note(QUESTION, None, [m18], _records(m18, verified=today), TODAY)
    assert "en son 30 Ekim 2026 tarihinde" in note and "yansımamış" not in note


def test_a_missing_date_is_said_and_never_filled_in():
    m18, m20 = _articles()
    records = _records(m18)  # m. 20 has no stored verification date
    note = currency_note.verification_note(QUESTION, None, [m18, m20], records, TODAY)
    assert "son karşılaştırma tarihi kayıtlarda yok" in note and "doğrulanamadı" in note
    assert "27 Ekim" not in note


def test_different_dates_report_the_range_and_judge_by_the_oldest():
    m18, m20 = _articles()
    records = {**_records(m18, verified=datetime(2026, 9, 18, tzinfo=timezone.utc), mbs=False, gazette=True), **_records(m20)}
    note = currency_note.verification_note(QUESTION, None, [m18, m20], records, TODAY)
    assert "18 Eylül 2026 ile 27 Ekim 2026 tarihleri arasında" in note
    assert "Mevzuat Bilgi Sistemi (mevzuat.gov.tr) ve Resmî Gazete" in note
    assert "18 Eylül 2026 sonrasında" in note


@pytest.mark.parametrize("question,as_of,expected", [
    ("Kıdem tazminatı şartları nelerdir?", None, False),     # currency not asked
    ("İş Kanunu 18. madde güncel hali nedir?", None, True),
    ("Kıdem tazminatı şartları nelerdir?", TODAY, True),     # explicit date of today
    ("Kıdem tazminatı şartları nelerdir?", date(2020, 1, 1), False),  # historical version: not today's currency
])
def test_the_note_appears_only_when_currency_is_asked(question, as_of, expected):
    m18, _ = _articles()
    assert (currency_note.verification_note(question, as_of, [m18], _records(m18), TODAY) is not None) is expected


def test_decisions_alone_get_no_legislation_note():
    decision = court_decision_context()
    assert currency_note.verification_note(QUESTION, None, [decision], {}, TODAY) is None


@pytest.mark.parametrize("text,expected", [
    ("30 Ekim 2026 tarihi itibarıyla", date(2026, 10, 30)), ("14 şubat 2025", date(2025, 2, 14)),
    ("30.10.2026 itibarıyla", date(2026, 10, 30)), ("31 Şubat 2026", None), ("tarih yok", None),
])
def test_question_dates(text, expected):
    assert currency_note.question_date(text) == expected


def test_the_pipeline_attaches_the_note_only_to_a_grounded_answer_citing_legislation(monkeypatch):
    m18, m20 = _articles()
    monkeypatch.setattr(currency_note, "fetch_verification_records", lambda ids: _records(m18, m20))
    request = SimpleNamespace(question=QUESTION, as_of=None)
    grounded = pipeline._with_verification_note(request, VerifiedAnswer("Cevap.", (m18, m20), ()))
    assert grounded.verification_note and "27 Ekim 2026" in grounded.verification_note
    assert grounded.text == "Cevap."  # the proven text is untouched
    ungrounded = pipeline._with_verification_note(request, VerifiedAnswer("Cevap.", (m18,), ("K9",), verification_note="eski"))
    assert ungrounded.verification_note is None
    plain = pipeline._with_verification_note(SimpleNamespace(question="Kıdem nedir?", as_of=None),
                                             VerifiedAnswer("Cevap.", (m18,), ()))
    assert plain.verification_note is None


def test_a_database_error_degrades_to_the_missing_date_statement(monkeypatch):
    import psycopg
    m18, _ = _articles()

    def broken(ids):
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(currency_note, "fetch_verification_records", broken)
    answer = pipeline._with_verification_note(SimpleNamespace(question=QUESTION, as_of=None), VerifiedAnswer("C.", (m18,), ()))
    assert "kayıtlarda yok" in answer.verification_note


def test_a_live_match_today_counts_as_verified_today():
    m18, m20 = _articles()
    live = {str(m18.source_id): currency_note.SAME, str(m20.source_id): currency_note.SAME}
    note = currency_note.verification_note(QUESTION, None, [m18, m20], _records(m18, m20), TODAY, live)
    assert "en son 30 Ekim 2026 tarihinde" in note and "yansımamış" not in note


def test_a_live_mismatch_is_reported_and_the_old_date_stays():
    m18, m20 = _articles()
    live = {str(m18.source_id): currency_note.SAME, str(m20.source_id): currency_note.DIFFERENT}
    note = currency_note.verification_note(QUESTION, None, [m18, m20], _records(m18, m20), TODAY, live)
    assert "27 Ekim 2026 ile 30 Ekim 2026 tarihleri arasında" in note
    assert "4857 sayılı Kanun m. 20 için kayıtlı metin Mevzuat Bilgi Sistemi'ndeki metinle eşleşmedi" in note
    assert "kayıt değiştirilmedi" in note


def test_an_unreachable_portal_says_up_to_which_date_it_was_verified():
    m18, _ = _articles()
    note = currency_note.verification_note(QUESTION, None, [m18], _records(m18), TODAY,
                                           {str(m18.source_id): currency_note.UNREACHABLE})
    assert "en son 27 Ekim 2026 tarihinde" in note
    assert "Bugün Mevzuat Bilgi Sistemi'ne ulaşılamadığı için 4857 sayılı Kanun m. 18 yeniden karşılaştırılamadı" in note


def test_recheck_compares_the_official_article_and_never_rewrites_a_differing_text(monkeypatch):
    from contextlib import contextmanager
    rows = [{"id": "a", "raw_text": "Madde 18 - Otuz veya daha fazla işçi...", "law_no": "4857", "article_no": "18"},
            {"id": "b", "raw_text": "Madde 20 - Eski metin.", "law_no": "4857", "article_no": "20"},
            {"id": "c", "raw_text": "Madde 1 - Başka kanun.", "law_no": "6098", "article_no": "1"}]
    updates, fetched = [], []

    class Connection:
        def execute(self, sql, params=None):
            if "UPDATE legal_sources" in sql:
                updates.append(params["id"])
            return SimpleNamespace(fetchall=lambda: rows)

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr("api.db.database_connection", connect)
    monkeypatch.setattr("api.db.admin_database_connection", connect)
    official = {"18": "MADDE 18 — Otuz veya daha fazla işçi...", "20": "Madde 20 - Yeni metin."}

    def fetch_law(law):
        fetched.append(law)
        if law == "6098":
            raise ValueError("portal down")
        return SimpleNamespace(pdf_url="https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf"), "tam metin"

    statuses = currency_note.recheck_official(["a", "b", "c"], fetch_law=fetch_law,
                                              extract=lambda full, article: official[article])
    assert statuses == {"a": "same", "b": "different", "c": "unreachable"}
    assert updates == ["a"]  # only the matching text gets today's date; the differing one is left as it is
    assert fetched == ["4857", "6098"]  # one official request per law


def test_the_pipeline_rechecks_only_stale_articles_and_reports_today(monkeypatch):
    m18, m20 = _articles()
    today_check = datetime.combine(date.today(), datetime.min.time()).astimezone()
    records = {**_records(m18), **_records(m20, verified=today_check)}
    asked = []
    monkeypatch.setattr(currency_note, "fetch_verification_records", lambda ids: records)
    monkeypatch.setattr(pipeline, "_live_recheck_allowed", lambda request, answer: True)
    monkeypatch.setattr(currency_note, "recheck_official",
                        lambda ids: asked.extend(ids) or {str(i): currency_note.SAME for i in ids})
    answer = pipeline._with_verification_note(SimpleNamespace(question=QUESTION, as_of=None),
                                              VerifiedAnswer("C.", (m18, m20), ()))
    assert asked == [m18.source_id]  # m. 20 was already compared today
    assert f"en son {currency_note.turkish_date(date.today())} tarihinde" in answer.verification_note


def test_a_crashing_recheck_is_reported_as_not_reached(monkeypatch):
    m18, _ = _articles()
    monkeypatch.setattr(currency_note, "fetch_verification_records", lambda ids: _records(m18))
    monkeypatch.setattr(pipeline, "_live_recheck_allowed", lambda request, answer: True)

    def boom(ids):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(currency_note, "recheck_official", boom)
    answer = pipeline._with_verification_note(SimpleNamespace(question=QUESTION, as_of=None), VerifiedAnswer("C.", (m18,), ()))
    assert "ulaşılamadığı için" in answer.verification_note and "27 Ekim 2026" in answer.verification_note


HEADER = ("İŞ KANUNU\n\nKanun Numarası : 4857\nKabul Tarihi : 22/5/2003\n"
          "Yayımlandığı Resmî Gazete : Tarih: 10/6/2003 Sayı: 25134\nYayımlandığı Düstur : Tertip: 5 Cilt: 42\n")


def test_the_law_identity_is_read_only_from_the_official_header():
    from datetime import date

    from api.ai import currency_note
    identity = currency_note.law_identity(HEADER, "4857")
    assert identity == {"accepted": date(2003, 5, 22), "gazette_date": date(2003, 6, 10), "gazette_no": "25134"}
    assert currency_note.law_identity(HEADER, "6098") == {}  # another law's header states nothing for this one
    assert currency_note.law_identity("Madde 1 - metin", "4857") == {}


def test_the_identity_sentence_states_only_what_the_header_carries():
    from datetime import date

    from api.ai import currency_note
    sentence = currency_note.identity_sentence({"4857": {
        "accepted": date(2003, 5, 22), "gazette_date": date(2003, 6, 10), "gazette_no": "25134",
        "url": "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf"}})
    assert "kabul tarihi 22 Mayıs 2003" in sentence and "Resmî Gazete 10 Haziran 2003, sayı 25134" in sentence
    assert "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf" in sentence
    assert currency_note.identity_sentence({}) == "" and currency_note.identity_sentence({"1": {}}) == ""


def test_an_unreachable_portal_yields_no_identity_instead_of_a_guess():
    from api.ai import currency_note

    def down(law):
        raise OSError("portal down")
    assert currency_note.fetch_law_identities(["4857"], fetch_law=down) == {}
    assert currency_note.asks_identity("Kanunun kabul tarihi, Resmî Gazete sayısı ve URL'si nedir?")
    assert not currency_note.asks_identity("Kıdem tazminatı nasıl hesaplanır?")


def test_sentences_claiming_the_official_source_was_unreachable_are_dropped_once_the_identity_is_read():
    from api.ai import currency_note
    text = ("4857 sayılı İş Kanunu'nun 17. maddesinin resmi kaynağını doğrulayamam. Kaynak yalnızca madde numarasını ve metnini içermektedir.\n\n"
            "Kötü niyet tazminatı bildirim süresine ait ücretin üç katıdır. İşçi için kıdem şartı aranmaz.")
    out = currency_note.drop_cannot_reach_sentences(text)
    assert "doğrulayamam" not in out and "yalnızca madde numarasını" not in out
    assert "Kötü niyet tazminatı bildirim süresine ait ücretin üç katıdır." in out and "kıdem şartı" in out
    assert out.count("\n\n") == 0 or "Kötü niyet" in out
