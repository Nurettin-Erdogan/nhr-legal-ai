"""Narrow, explicitly ungrounded concept definitions for normal public chat.

Never used for a private scope, a personal result, a citation or a current
amount/deadline. Search remains first; this is not a second legal-advice path.
"""
import json
import re

from api.ai.providers import AIProviderError
from api.ai.query_vocabulary import standalone_definition, expand_search_terms, has_search_abbreviation
from api.ai import synthesis

_DOMAIN = re.compile(r"hukuk|sözleşme|tazminat|kira|miras|vergi|sigorta|mevzuat|içtihat|emsal|"
                     r"arabulucu|dava|mahkeme|avukat|borç|alacak|tapu|mülkiyet|nafaka|velayet|"
                     r"tüketici fiyat endeksi|üretici fiyat endeksi")
_RISK = re.compile(r"\d|%|₺|\b(?:madde|sayılı|kaç|güncel|oran|tutar|süre|zamanaşımı|"
                   r"hak düşürücü|başvuru|hesap|ödeme|ücret|maaş)\w*\b")
_UNSAFE = re.compile(
    r"\d|[%₺€$]|https?://|www\.|[\[\]<>@]|"
    r"\b(?:madde\w*|sayılı|yargıtay|danıştay|zorunlu\w*|zorunda\w*|kesinlikle|mutlaka|"
    r"daima|ödenir|ödenmelidir|ödemelisiniz|başvurmalısınız|alabilirsiniz|alamazsınız|"
    r"kazanırsınız|kaybedersiniz|hakkınız|yükümlüsünüz)\b|"
    r"\b(?:gün|hafta|ay|yıl|sene|saat|yüzde|binde|lira|tutar)\w*\b|"
    r"\b(?:gerekir|ödenmel\w*|ödeye\w*|istenebilir|alınır|verilir)\b|talep ed|başvur|"
    r"\b(?:bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|otuz|altmış|doksan)\s+"
    r"(?:gün|ay|yıl|hafta|saat|lira|yüzde)\w*\b|her koşulda|hak kazan|hakkı vardır",
    re.IGNORECASE,
)
INSTRUCTION = """Yalnız verilen hukukla ilişkili kavramın genel anlamını sade Türkçeyle açıkla.
Bu açıklama kaynaklarla doğrulanmış hukuki görüş DEĞİLDİR. En çok üç kısa cümle yaz.
Kişisel hak, hukuki sonuç, yapılacak işlem, zorunluluk, süre, oran, tutar, güncel değer,
kanun/madde numarası, mahkeme kararı veya atıf VERME. Bir kullanım örneği ekleyerek kapsamı genişletme.
İnternet veya araç kullanma. Kaynak araştırdığını ya da doğrulandığını iddia etme.
Bu sınırlar içinde güvenilir bir kavram açıklaması yazamıyorsan answer:null döndür.
Yalnız JSON: {"answer":"Kısa kavram açıklaması."}."""

# This source-free exception is not a second legal synthesis path. A denylist
# cannot establish that arbitrary prose contains no legal outcome. Only reviewed
# definitions may pass it; everything else stays on the source-checked path.
_REVIEWED_DEFINITIONS = {
    "tüketici fiyat endeksi": (
        "TÜFE, Tüketici Fiyat Endeksi'nin kısaltmasıdır.",
        "TÜFE, tüketicilerin satın aldığı ürün ve hizmetlerin fiyat değişimini izleyen bir endekstir.",
    ),
    "üretici fiyat endeksi": (
        "ÜFE, Üretici Fiyat Endeksi'nin kısaltmasıdır.",
    ),
    "sözleşme": (
        "Sözleşme, tarafların karşılıklı ve birbirine uygun irade açıklamalarıyla kurulan anlaşmadır.",
    ),
    "arabuluculuk": (
        "Arabuluculuk, tarafların uyuşmazlıklarını tarafsız bir üçüncü kişinin yardımıyla görüşerek çözmeye çalıştığı bir yöntemdir.",
    ),
}


def _reviewed_answers(question: str) -> tuple[str, ...]:
    term = re.sub(r"\s+(?:nedir|ne demek|ne anlama gelir)[\s?.!]*$", "",
                  expand_search_terms(question).strip())
    return _REVIEWED_DEFINITIONS.get(term, ())


def eligible_definition(question: str) -> bool:
    q = question.replace("İ", "i").lower()
    return (standalone_definition(question) and not _RISK.search(q)
            and bool(has_search_abbreviation(q) or _DOMAIN.search(expand_search_terms(q))))


def generate_definition(provider, question: str) -> str | None:
    reviewed = _reviewed_answers(question)
    if not eligible_definition(question) or not reviewed:
        return None
    try:
        result = synthesis._json(provider.generate(
            system_instruction=(INSTRUCTION + "\nYalnız aşağıdaki gözden geçirilmiş tanımlardan birini "
                                "aynen seç; uygun değilse answer:null döndür:\n"
                                + json.dumps(reviewed, ensure_ascii=False)),
            prompt=json.dumps({"question": question}, ensure_ascii=False)))
    except (AIProviderError, ValueError, TypeError, RecursionError):
        return None
    if not isinstance(result, dict) or set(result) != {"answer"}:
        return None
    text = result["answer"]
    if (not isinstance(text, str) or not 15 <= len(text.strip()) <= 1200
            or _UNSAFE.search(text) or synthesis._FOREIGN_SCRIPT.search(text)
            or synthesis._INJECTION.search(text) or len(synthesis._sentences(text)) > 3):
        return None
    # Exact comparison intentionally rejects appended clauses, topic drift and
    # equivalent-looking but unreviewed legal conclusions. No model can approve
    # its own unsupported output merely by calling it a definition.
    text = text.strip()
    return text if text in reviewed else None
