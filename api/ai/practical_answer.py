"""Kaynaklı cevabın yanında eksik hesap girdisini sorar; oran veya hukuki izin üretmez.

Kanıt metni/atıflar değişmez. Sayılar yalnız kullanıcının kendi sorularından gelir;
modelin yorumladığı sorudan tutar/oran alınmaz. Hesap Decimal ile yapılır ve açıkça
kullanıcının verdiği oranla yapılan aritmetik olarak sunulur, yasal tavan değildir.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dataclasses import dataclass
import re
from collections.abc import Sequence

from api.ai.relevance import question_intent
from api.ai.verification import VerifiedAnswer
from api.ai.providers import AIProviderError

_MONEY = re.compile(
    r"(?<![\w/%.,-])(?P<value>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[,.]\d{1,2})?)"
    r"\s*(?P<scale>bin|milyon)?\s*(?P<currency>tl|₺|lira)?(?![\w.,/])", re.I)
_RATE = re.compile(r"(?:%\s*|\byüzde\s+)(\d+(?:[,.]\d{1,2})?)(?!\d|[,.]\d)", re.I)
_MONTH = re.compile(r"ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık", re.I)
_PERIOD = re.compile(r"\b(?:19|20)\d{2}\b")
_RENEWAL_DATE = re.compile(r"\b(?:\d{1,2}[./-])?\d{1,2}[./-](?:19|20)\d{2}\b|\b(?:19|20)\d{2}-\d{2}(?:-\d{2})?\b")
_PROPERTY = re.compile(r"\b(?:konut|ev|daire|çatılı|işyeri|iş yeri|dükkan|dükkân)\b", re.I)
_CALCULATION = re.compile(r"ne kadar|kaç|yüzde|%|en fazla|azami|üst sınır|hesap", re.I)
_LEGAL_LIMIT = re.compile(r"en fazla|azami|üst sınır|yasal|hukuk|yapabil|geçerli|uygun|mümkün|hakkım", re.I)


@dataclass(frozen=True)
class RentCalculationProvider:
    """Aritmetik/eksik girdi yanıtını LLM cevabı diye etiketleme."""
    basis_text: str
    name: str = "calculation"
    model: str = "decimal+verified-basis-v1"

    def generate(self, *, system_instruction: str, prompt: str) -> str:
        raise AIProviderError("Hesap akışı dil modeli çağrısı yapmaz")


def rent_basis(contexts, *, question: str, user_question: str,
               prior_questions: Sequence[str] = ()) -> RentCalculationProvider | None:
    from api.ai.verification import verify_answer
    from api.ai.source_support import source_sentences

    # Tutarı kullanıcı belgesinden çıkarmak farklı bir iştir; bu kısa yol özel
    # belge/karar kapsamını daraltamaz. Yalnız getirilen TBK 344 cümleleri kullanılır.
    if any(c.source_type != "legislation" or c.verification != "official"
           or c.law_no != "6098" or c.article_no != "344" for c in contexts):
        return None
    lines = [f"{sentence} [K{index}]" for index, context in enumerate(contexts, 1)
             if context.source_type == "legislation" and context.verification == "official"
             and context.law_no == "6098" and context.article_no == "344"
             for sentence in source_sentences(context)]
    if not lines:
        return None
    basis = verify_answer("\n".join(lines), contexts, question=question)
    if not rent_summary(basis, question=question, user_question=user_question, prior_questions=prior_questions):
        return None
    return RentCalculationProvider(basis_text="\n".join(lines))


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", ".") if "," in value or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value)
                   else value)


def _amounts(text: str) -> set[Decimal]:
    amounts = set()
    for match in _MONEY.finditer(text):
        value = match["value"]
        # Bare dates, article numbers, ages and percentages are not rent amounts.
        if len(re.sub(r"\D", "", value)) > 12:
            continue
        if not (match["scale"] or match["currency"] or 5 <= len(re.sub(r"\D", "", value)) <= 7):
            continue
        try:
            amount = _decimal(value) * {"bin": 1000, "milyon": 1000000, "": 1}[(match["scale"] or "").lower()]
        except InvalidOperation:
            continue
        if amount > 0:
            amounts.add(amount)
    return amounts


def has_calculation_inputs(user_question: str, prior_questions: Sequence[str] = ()) -> bool:
    """Only explicit user-supplied arithmetic bypasses natural legal synthesis.

    Asking how a rule works is not a request for a topic-specific canned reply.
    A missing legal rate must never be guessed or replaced with a model rate.
    """
    return bool(_RATE.search(user_question)) and any(
        _amounts(text) for text in (user_question, *prior_questions)
    )


def _money(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ",.2f").replace(",", "_").replace(".", ",").replace("_", ".").removesuffix(",00") + " TL"


def rent_summary(answer: VerifiedAnswer, *, question: str, user_question: str,
                 prior_questions: Sequence[str] = ()) -> tuple[str, ...]:
    """Eksik TÜFE/olay verisini madde metniyle doldurma. Resmî TBK 344 kanıtı şart."""
    intent = question_intent(question)
    if not answer.grounded or intent is None or intent.name != "rent_increase":
        return ()
    # Genel mevzuat, itiraz ve başvuru sorusunu bir kira hesaplayıcısına çevirme.
    if not _CALCULATION.search(question) and not _amounts(user_question):
        return ()
    if re.search(r"ne yap\w*|nasıl itiraz|itiraz ed|dava aç|tahliye", question, re.I):
        return ()
    if not any(c.source_type == "legislation" and c.verification == "official"
               and c.law_no == "6098" and c.article_no == "344" for c in answer.contexts):
        return ()
    # Bu yalnız hesap girdisi yardımcısıdır. Yeni hukuk iddiası eklemez, genel
    # "zam yapabilirsiniz" hükmü vermez; resmî dayanak cevabın kaynaklarında kalır.
    questions = [user_question, *reversed(prior_questions)]
    amount = None
    for text in questions:
        amounts = _amounts(text)
        if amounts:
            amount = next(iter(amounts)) if len(amounts) == 1 else None
            break
    rates = {Decimal(value.replace(",", ".")) for value in _RATE.findall(user_question)
             if len(re.sub(r"\D", "", value)) <= 8}
    parts = []
    if amount is not None and len(rates) == 1:
        rate = next(iter(rates))
        increase = (amount * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        parts.append(f"Verdiğiniz %{format(rate, 'f').replace('.', ',')} oranıyla hesap: {_money(amount)} kira "
                     f"{_money(amount + increase)} olur; artış {_money(increase)}.")
        if not _LEGAL_LIMIT.search(question):
            return tuple(parts)  # saf aritmetik sorusunda gereksiz hukuki uyarı/ay sorusu yok
        parts[-1] += " Bu hesap, oranın yasal üst sınır olduğunu göstermez."
        # The user supplied the rate. Do not fall through to the missing-rate
        # branch and ask for exactly the percentage we have just calculated.
        return tuple(parts)
    joined = " ".join(questions)
    missing = []
    if amount is None:
        missing.append("mevcut kira tutarını")
    if not ((_MONTH.search(joined) and _PERIOD.search(joined)) or _RENEWAL_DATE.search(joined)):
        missing.append("sözleşmenin hangi ay/yıl yenilendiğini")
    if not _PROPERTY.search(joined):
        missing.append("konut mu, çatılı işyeri mi olduğunu")
    if missing:
        prefix = f"{_money(amount)} için net üst sınırı hesaplayabilmem için " if amount is not None else "Hesaplayabilmem için "
        parts.append(prefix + ", ".join(missing) + " yazar mısınız?")
    elif all(c.source_type == "legislation" and c.law_no == "6098" and c.article_no == "344"
             for c in answer.contexts):
        parts.append("Bu yenileme dönemi için doğrulanmış TÜFE oranı getirilen kaynaklarda yok. Oranı paylaşırsanız "
                     "artış tutarını ve yeni kirayı hesaplayabilirim; şu an bir yüzdeyi yasal tavan diye söyleyemem.")
    return tuple(parts)
