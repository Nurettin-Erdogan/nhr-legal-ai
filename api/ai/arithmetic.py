"""Explicit arithmetic is not a legal finding. No eval, formula inference or AI."""
from decimal import Decimal, InvalidOperation, localcontext
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
