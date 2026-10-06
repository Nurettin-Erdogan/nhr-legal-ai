"""Takip sorusunun tek başına soruya çevrilmesi ve cevap uyarıları (2026-10-05 ölçümlerinden)."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from api.ai.conversation_history import (
    accept_rewrite,
    prior_questions_from_rows,
    standalone_question,
)
from api.ai.explanation import stale_decisions_notice, validate_claims
from api.ai.rag import RAGContext
from api.ai.verification import VerifiedAnswer

PRIOR = ("İhbar tazminatı nedir?",)
FOLLOW_UP = "Peki bunun zamanaşımı süresi kaç yıl?"


def _context(**overrides) -> RAGContext:
    values = dict(
        chunk_id=uuid4(), source_id=uuid4(), source_type="court_decision", title="Karar", source_url=None,
        authority=None, court_name="Yargıtay", chamber="9. Hukuk Dairesi", docket_no="2011/1", decision_no="2013/2",
        decision_date=date(2013, 10, 2), law_name=None, law_no=None, article_no=None, article_title=None,
        content="İhbar tazminatı davaları on yıllık zamanaşımına tabidir.", rank=1.0,
    )
    values.update(overrides)
    return RAGContext(**values)


class _Provider:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        self.calls += 1
        return self.reply


def test_follow_up_is_completed_with_the_topic_of_the_previous_question():
    assert accept_rewrite("İhbar tazminatının zamanaşımı süresi kaç yıl?", FOLLOW_UP, PRIOR) == (
        "İhbar tazminatının zamanaşımı süresi kaç yıl?"
    )


def test_rewrite_may_not_invent_a_topic_number_or_drop_the_users_words():
    # Konu uydurma: önceki sorularda "kıdem" ve "işveren" yok.
    assert accept_rewrite("Kıdem tazminatında işverenin zamanaşımı süresi kaç yıl?", FOLLOW_UP, PRIOR) is None
    # Sayı ekleme (cevabı soruya gömme).
    assert accept_rewrite("İhbar tazminatının zamanaşımı süresi 5 yıl mı?", FOLLOW_UP, PRIOR) is None
    # Kullanıcının sorduğu şey ("zamanaşımı") düşmüş.
    assert accept_rewrite("İhbar tazminatının süresi kaç yıl?", FOLLOW_UP, PRIOR) is None


def test_rewrite_that_changes_nothing_or_just_prepends_the_old_question_is_rejected():
    assert accept_rewrite(FOLLOW_UP, FOLLOW_UP, PRIOR) is None
    # Konu değişmişken eski soruyu başa eklemek aramayı eski konuya taşır.
    assert accept_rewrite("İhbar tazminatı nedir? Kira artış oranı nasıl belirlenir?", "Kira artış oranı nasıl belirlenir?", PRIOR) is None
    assert accept_rewrite("İhbar tazminatı nedir?", FOLLOW_UP, PRIOR) is None


def test_harmless_inflection_words_do_not_block_a_rewrite():
    rewritten = accept_rewrite(
        "Fazla mesai ücretinin ispatı için tanık yeterli midir?", "Tanık yeterli mi?", ("Fazla mesai ücreti nasıl ispatlanır?",)
    )
    assert rewritten == "Fazla mesai ücretinin ispatı için tanık yeterli midir?"


def test_standalone_question_fails_closed_on_bad_model_output():
    assert standalone_question(_Provider("bu JSON değil"), FOLLOW_UP, PRIOR) is None
    assert standalone_question(_Provider('{"question": 42}'), FOLLOW_UP, PRIOR) is None
    provider = _Provider('{"question": "İhbar tazminatının zamanaşımı süresi kaç yıl?"}')
    assert standalone_question(provider, FOLLOW_UP, PRIOR) == "İhbar tazminatının zamanaşımı süresi kaç yıl?"
    # Önceki soru yoksa model hiç çağrılmaz.
    idle = _Provider("{}")
    assert standalone_question(idle, FOLLOW_UP, ()) is None and idle.calls == 0


def test_prior_questions_include_turns_whose_answer_was_not_grounded():
    rows = [
        {"role": "user", "content": "İhbar tazminatı nedir?"},
        {"role": "assistant", "content": "Yeterli bilgi yok.", "metadata": {"grounded": False}},
        {"role": "user", "content": "Peki süresi?"},
    ]
    assert prior_questions_from_rows(rows) == ("İhbar tazminatı nedir?", "Peki süresi?")


def test_answer_resting_only_on_old_decisions_gets_a_date_notice():
    old = VerifiedAnswer(text="X. [K1]", contexts=(_context(),), unverified_markers=())
    notice = stale_decisions_notice(old, today=date(2026, 10, 5))
    assert notice and "02.10.2013" in notice and "güncelliğini kontrol edin" in notice
    recent = VerifiedAnswer(text="X. [K1]", contexts=(_context(decision_date=date(2021, 3, 23)),), unverified_markers=())
    assert stale_decisions_notice(recent, today=date(2026, 10, 5)) is None
    # Mevzuat maddesine de dayanan cevap uyarılmaz: güncel metin zaten atıfta.
    statute = _context(source_type="legislation", decision_date=None, law_no="4857", article_no="17")
    mixed = VerifiedAnswer(text="X. [K1] Y. [K2]", contexts=(_context(), statute), unverified_markers=())
    assert stale_decisions_notice(mixed, today=date(2026, 10, 5)) is None


def test_repeated_explanation_claims_are_collapsed():
    answer = VerifiedAnswer(
        text="Anlaşmalı boşanma için eşlerin anlaşmayı hâkimin onayına sunması gerekir. [K1]",
        contexts=(_context(content="Anlaşmalı boşanma için eşlerin anlaşmayı hâkimin onayına sunması gerekir."),),
        unverified_markers=(),
    )
    claim = '{"text": "Anlaşmalı boşanma için eşler anlaşmayı hâkimin onayına sunmalıdır.", "sources": [1]}'
    checked = validate_claims('{"claims": [' + ", ".join([claim] * 4) + "]}", answer, "Anlaşmalı boşanma için eşler ne yapmalı?")
    assert checked is not None and len(checked) == 1


def test_statute_article_is_rebuilt_in_source_order_not_search_rank_order():
    from api.ai.evidence_selection import preserve_statutory_scope

    def part(index: int, text: str) -> RAGContext:
        return _context(
            source_type="legislation", court_name=None, chamber=None, docket_no=None, decision_no=None, decision_date=None,
            law_name="İŞ KANUNU", law_no="1475", article_no="14", chunk_index=index, content=text,
        )

    first = part(0, "Kıdem tazminatı işçinin kıdem süresine göre işverence ödenir.")
    second = part(1, "Kıdem tazminatı her geçen tam yıl için otuz günlük ücret tutarında hesaplanır.")
    # Arama ikinci parçayı önce getirdi (K1 = maddenin ikinci parçası).
    rebuilt = preserve_statutory_scope(
        "Kıdem tazminatı her geçen tam yıl için otuz günlük ücret tutarında hesaplanır. [K1]",
        [second, first], "Kıdem tazminatı nasıl hesaplanır?",
    )
    assert rebuilt.split("\n\n") == [
        "Kıdem tazminatı işçinin kıdem süresine göre işverence ödenir. [K2]",
        "Kıdem tazminatı her geçen tam yıl için otuz günlük ücret tutarında hesaplanır. [K1]",
    ]


def test_filler_words_of_the_follow_up_need_not_survive_the_rewrite():
    # "için" konu taşımaz; yeniden yazımda düşmesi iyi bir yorumu geçersiz kılmamalı.
    prior = ("Kira sözleşmesinde kira artış oranı nasıl belirlenir?",)
    rewritten = "Kira sözleşmesinde kira artış oranı belirlenirken dava açmak şart mı?"
    assert accept_rewrite(rewritten, "Peki bunun için dava açmak şart mı?", prior) == rewritten
    # Kullanıcının sorduğu şey ("dava açmak") düşerse yine reddedilir.
    assert accept_rewrite("Kira sözleşmesinde kira artış oranı belirlenirken şart mı?", "Peki bunun için dava açmak şart mı?", prior) is None


def test_a_legal_term_absent_from_the_conversation_may_not_be_slipped_in():
    prior = ("İtirazın iptali davası hangi sürede açılır?",)
    question = "Bu süre ne zaman başlar?"
    # Model sürenin niteliğini kendisi adlandırıyor (zamanaşımı / hak düşürücü): kullanıcıya böyle gösterilemez.
    assert accept_rewrite("İtirazın iptali davasının zamanaşımı süresi ne zaman başlar?", question, prior) is None
    assert accept_rewrite("İtirazın iptali davasının hak düşürücü süresi ne zaman başlar?", question, prior) is None
    assert accept_rewrite("İtirazın iptali davasında faiz süresi ne zaman başlar?", question, prior) is None
    # Yalnız önceki sorunun sözcükleriyle tamamlanan hâli kabul edilir.
    good = "İtirazın iptali davası açma süresi ne zaman başlar?"
    assert accept_rewrite(good, question, prior) == good


def test_the_previous_question_joined_with_and_is_accepted_but_pasted_as_a_second_question_is_not():
    prior = ("Tüketici ayıplı malda hangi haklara sahiptir?",)
    follow_up = "Satıcı bunu reddederse ne yapılır?"
    joined = "Tüketici ayıplı malda hangi haklara sahiptir ve satıcı bunu reddederse ne yapılır?"
    # Model iki soruyu bağlı görüp "ve" ile birleştirmiş: yeni sorunun sözcükleri eksiksiz, konu önceki sorudan.
    assert accept_rewrite(joined, follow_up, prior) == joined
    # İki ayrı soru cümlesi olarak yapıştırma (konu değişmiş olabilir) reddedilir.
    assert accept_rewrite("Tüketici ayıplı malda hangi haklara sahiptir? Satıcı bunu reddederse ne yapılır?", follow_up, prior) is None
    # Eski soru ortada/sonda aynen duruyorsa da reddedilir.
    assert accept_rewrite("Satıcı bunu reddederse, tüketici ayıplı malda hangi haklara sahiptir", follow_up, prior) is None


def test_an_explanation_may_not_assert_an_absence_the_source_does_not_state():
    # Madde "en az otuz gün" der; "istisna yoktur" demez. Model bu cümleyi üretti, model denetçisi de onayladı.
    import json

    from api.ai.explanation import unsupported_absolute

    quote = "Kiracıya verilecek süre en az on gün, konut ve çatılı işyeri kiralarında ise en az otuz gündür."
    answer = VerifiedAnswer(text=f"{quote} [K1]", contexts=(_context(content=quote),), unverified_markers=())
    good = {"text": "Konut ve çatılı işyeri kiralarında kiracıya verilecek süre en az otuz gündür.", "sources": [1]}
    invented = {"text": "Bu süreler genel bir kural olup olaya özgü istisnalar söz konusu değildir.", "sources": [1]}
    question = "Kiracıya verilecek süre en az kaç gün olmalı?"

    checked = validate_claims(json.dumps({"claims": [good, invented]}, ensure_ascii=False), answer, question)
    assert checked is not None and [claim["text"] for claim in checked] == [good["text"]]
    # Geriye alıntıyı kapsayan iddia kalmıyorsa açıklama tümüyle düşer; kaynak cümle olduğu gibi gösterilir.
    assert validate_claims(json.dumps({"claims": [invented]}, ensure_ascii=False), answer, question) is None

    assert unsupported_absolute("Başka hiçbir koşul aranmaz.", quote) == "hiçbir"
    assert unsupported_absolute("Süre her durumda otuz gündür.", quote) == "her durumda"
    # Kaynak yokluğu kendisi söylüyorsa açıklama da söyleyebilir.
    assert unsupported_absolute("Yer altı işlerinde kıdem şartı aranmaz.", "Yer altı işlerinde çalışan işçilerde kıdem şartı aranmaz.") is None
    assert unsupported_absolute("Süre en az otuz gündür.", quote) is None
