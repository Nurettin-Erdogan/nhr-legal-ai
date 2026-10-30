"""Explicit arithmetic is not a legal finding. No eval, formula inference or AI."""
from decimal import Decimal, InvalidOperation, localcontext
from collections.abc import Sequence
import re


_NUMBER = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_EXPRESSION = re.compile(rf"(?P<left>{_NUMBER})\s*(?P<op>[+*/x×÷-])\s*(?P<right>{_NUMBER})", re.I)
_FILLER = re.compile(r"\b(?:hesapla|hesap|kac|ne|eder|esittir|sonuc|nedir|yapar|sadece|lutfen|ornek)\b")


def _decimal(value: str) -> Decimal:
    if "," in value or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "").replace(",", ".")
    return Decimal(value)


def arithmetic_reply(question: str) -> str | None:
    """Only one fully explicit binary expression, never a legal word problem.

    Unknown words, rates, dates, currency, conditions, or a question about a
    right all go through the normal source-bound path instead.
    """
    if not isinstance(question, str) or len(question) > 160:
        return None
    text = question.replace("İ", "i").lower().translate(str.maketrans("çğıöşü", "cgiosu"))
    matches = list(_EXPRESSION.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    residue = text[:match.start()] + " " + text[match.end():]
    if _FILLER.sub("", residue).strip(" ?=:.!\t\r\n"):
        return None
    # Parser/resource ceiling only; not a model response/token budget.
    if len(match["left"]) > 40 or len(match["right"]) > 40:
        return None
    try:
        with localcontext() as context:
            context.prec = 90
            left, right = _decimal(match["left"]), _decimal(match["right"])
            op = match["op"].lower()
            if op in ("/", "÷") and right == 0:
                return "Sıfıra bölme tanımsızdır."
            if op == "+":
                value = left + right
            elif op == "-":
                value = left - right
            elif op in ("*", "x", "×"):
                value = left * right
            else:
                value = left / right
            fractional = value != value.to_integral_value()
            text = format(value, ",.8f" if fractional else ",.0f")
            if fractional:
                text = text.rstrip("0").rstrip(".")
            result = text.replace(",", "_").replace(".", ",").replace("_", ".")
            return ("Yaklaşık " if fractional and value != Decimal(text.replace(",", "")) else "") + result
    except (InvalidOperation, ArithmeticError):
        return None


def rent_percentage_reply(question: str, prior_questions: Sequence[str] = ()) -> str | None:
    """An explicitly supplied increase is arithmetic, not a legal rent ceiling.

    Strict vocabulary keeps legal, interest, tax, compound, foreign-currency and
    ambiguous questions on the evidence route. Only user statements supply the
    amount; an assistant's previous prose or a source example never does.
    """
    if not isinstance(question, str) or len(question) > 500:
        return None
    from api.ai.dialogue import user_inputs
    from api.ai.practical_answer import _amounts, _RATE, _MONEY
    from decimal import ROUND_HALF_UP

    def folded(value):
        return value.replace("İ", "i").lower().translate(str.maketrans("çğıöşü", "cgiosu"))

    text = folded(question)
    rates = list(_RATE.finditer(question))
    if len(rates) != 1 or len(rates[0][1]) > 10:
        return None
    if not re.search(r"\b(?:kac|ne kadar|hesapla\w*)\b", text):
        return None
    if not re.search(r"\b(?:artis\w*|artir\w*|zam\w*)\b", text):
        return None
    # No substantive/legal wording can be silently consumed by a calculator.
    residue = question[:rates[0].start()] + " " + question[rates[0].end():]
    current_amounts = _amounts(residue)
    for match in list(_MONEY.finditer(residue))[::-1]:
        if _amounts(match.group()):
            residue = residue[:match.start()] + " " + residue[match.end():]
    residue = folded(residue)
    allowed = re.compile(r"\b(?:ornek|hesap|hesapla\w*|kira(?:m|mi|yi|ya|si|siyle|siyla)?|icin|"
                         r"artis(?:la|i|iyla|iyla)?|artir(?:inca|irsak|ilirsa)|zam(?:la|mi)?|"
                         r"yap(?:ilirsa|arsak|arsam|inca|ilinca|arak)|tl|lira|ne|kadar|kac|olur|eder|yeni|"
                         r"mevcut|suanki|lutfen|sadece|tutar(?:i)?|toplam)\b")
    if allowed.sub("", residue).strip(" ?!.,:;\t\r\n"):
        return None
    inputs = user_inputs(question, prior_questions=prior_questions)
    if not any(re.search(r"\bkira\w*\b", folded(value)) for value in inputs):
        return None
    amount = None
    amount_input = None
    if current_amounts:
        if len(current_amounts) != 1:
            return None
        amount, amount_input = next(iter(current_amounts)), question
    else:
        for value in reversed(inputs[:-1]):
            if not re.search(r"\bkira\w*\b", folded(value)):
                continue
            candidates = _amounts(value)
            if not candidates and re.search(r"\d[\d.,]*\s*(?:tl\b|lira\b|₺|bin\b|eur\b|usd\b|euro\b|dolar\b)", value, re.I):
                return None  # an invalid/latest declaration cannot revive an older rent
            if candidates:
                if len(candidates) != 1:
                    return None
                amount, amount_input = next(iter(candidates)), value
                break
    if amount is None or amount_input is None:
        return None
    # Currency is never guessed from the country or corpus. A foreign unit
    # cannot be turned into TL by the legacy rent-number recogniser.
    if re.search(r"\b(?:usd|eur|dolar|euro)\b|[$€]", amount_input, re.I):
        return None
    suffix = " TL" if re.search(r"\b(?:tl|try|lira)\b|₺", amount_input, re.I) else ""
    with localcontext() as context:
        context.prec = 50
        rate = Decimal(rates[0][1].replace(",", "."))
        increase = (amount * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = amount + increase
    def formatted(value):
        return format(value, ",.2f").replace(",", "_").replace(".", ",").replace("_", ".").removesuffix(",00") + suffix
    return (f"Verdiğiniz %{format(rate, 'f').replace('.', ',')} artışla {formatted(amount)} kira "
            f"{formatted(total)} olur; artış {formatted(increase)}.")
