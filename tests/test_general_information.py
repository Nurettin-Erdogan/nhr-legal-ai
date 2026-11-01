import json
import pytest

from api.ai.general_information import eligible_definition, generate_definition
from api.ai.answer_kind import stored_answer_kind
from api.ai.conversation_history import history_turns_from_rows


class Provider:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({"answer": self.answer}, ensure_ascii=False)


@pytest.mark.parametrize("question", ["TÜFE nedir?", "tufe nedir?", "Sözleşme nedir?", "Arabuluculuk ne demek?"])
def test_only_plain_named_definitions_are_eligible(question):
    assert eligible_definition(question)


@pytest.mark.parametrize("question", [
    "Bu nedir?", "Benim hakkım nedir?", "Maaşım nedir?", "Tazminatım nedir?",
    "Kira artış oranı nedir?", "Güncel TÜFE nedir?", "Zamanaşımı süresi nedir?",
    "4857 madde 17 nedir?", "Yüzde 20 zam kaç lira?", "Pizza nedir?",
])
def test_risky_private_or_off_topic_questions_cannot_use_general_generation(question):
    provider = Provider("Kısa genel açıklama.")
    assert generate_definition(provider, question) is None
    assert provider.calls == []


@pytest.mark.parametrize("text", [
    "TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır.",
    "TÜFE, tüketicilerin satın aldığı ürün ve hizmetlerin fiyat değişimini izleyen bir endekstir.",
])
def test_plain_general_information_has_no_invented_citation_or_legal_result(text):
    provider = Provider(text)
    assert generate_definition(provider, "TÜFE nedir?") == text
    assert json.loads(provider.calls[0]["prompt"]) == {"question": "TÜFE nedir?"}


@pytest.mark.parametrize("text", [
    "Bugün TÜFE yüzde 20 oranındadır.", "Kira artışı yüzde yirmi olmak zorundadır.",
    "Bir ay içinde başvurmalısınız.", "Yargıtay bu hakkı tanımıştır.",
    "Şu madde gereğince tazminat alabilirsiniz.", "Açıklama burada. [K1]",
    "Açıklama https://example.test adresindedir.", "Kesinlikle hak kazanırsınız.",
    "TÜFE yüzde yirmidir.", "Yirmi gün sonra ödeme yapılır.",
    "Tazminat talep edilebilir.", "Ödemenin yapılması gerekir.",
])
def test_source_free_output_cannot_smuggle_rates_deadlines_or_authority(text):
    assert generate_definition(Provider(text), "TÜFE nedir?") is None


def test_general_information_survives_storage_but_is_not_legal_history_evidence():
    assert stored_answer_kind("general_information") == "general_information"
    assert stored_answer_kind("random") == "legal"
    assert history_turns_from_rows([
        {"role": "user", "content": "TÜFE nedir?"},
        {"role": "assistant", "content": "Genel açıklama.",
         "metadata": {"grounded": False, "answer_kind": "general_information"}},
    ]) == ()
    assert history_turns_from_rows([
        {"role": "user", "content": "TÜFE nedir?"},
        {"role": "assistant", "content": "Genel açıklama.",
         "metadata": {"grounded": True, "answer_kind": "general_information"}},
    ]) == ()


@pytest.mark.parametrize("text", [
    "TÜFE, tüketici fiyat endeksidir. İşverenin feshi tazminat hakkını doğurur.",
    "TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır. Her kiracı artışı kabul eder.",
    "TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır.\u200b",
    "ÜFE, Üretici Fiyat Endeksi'nin kısaltmasıdır.",
])
def test_definition_rejects_topic_drift_appended_claims_and_hidden_characters(text):
    assert generate_definition(Provider(text), "TÜFE nedir?") is None


def test_unreviewed_definition_never_spends_a_generation_call():
    provider = Provider("Bir hukuki sonuç.")
    assert generate_definition(provider, "Tazminat nedir?") is None
    assert provider.calls == []


@pytest.mark.parametrize("question,text", [
    ("Sözleşme nedir?", "Sözleşme, tarafların karşılıklı ve birbirine uygun irade açıklamalarıyla kurulan anlaşmadır."),
    ("Arabuluculuk ne demek?", "Arabuluculuk, tarafların uyuşmazlıklarını tarafsız bir üçüncü kişinin yardımıyla görüşerek çözmeye çalıştığı bir yöntemdir."),
])
def test_reviewed_definitions_remain_available(question, text):
    assert generate_definition(Provider(text), question) == text
