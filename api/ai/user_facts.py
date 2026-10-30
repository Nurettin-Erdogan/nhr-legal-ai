"""Typed, provenance-preserving USER event inputs, never legal evidence.

No model, network, corpus, entitlement, tax or cap inference lives here. A
calendar interval is ordinary declared-date arithmetic (exclusive elapsed days),
not a determination of legally creditable service or compensation.
"""
from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from api.ai.dialogue import user_inputs
from api.ai.rag import HistoryTurn


_MONTHS = {name: index for index, name in enumerate(
    ("ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"), 1)}
_DATES = (
    re.compile(r"(?<!\d)(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{4})(?!\d)"),
    re.compile(r"(?<!\w)(?P<day>\d{1,2})\s+(?P<month>" + "|".join(_MONTHS) + r")\s+(?P<year>\d{4})(?!\d)"),
)
_AMOUNT = re.compile(
    r"(?<![\w/.,-])(?P<number>\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
    r"\s*(?P<scale>bin|milyon)?\s*(?P<currency>tl|try|lira|₺|eur|euro|usd|dolar)?(?![\w/.,])", re.I)
_PAY = re.compile(r"\b(?:brut|net|maas\w*|ucret\w*)\b")
_BASIS = re.compile(r"\b(?:brut|net)\b")
_OTHER_PAYMENT = re.compile(r"\b(?:yemek|yol|prim\w*|ikramiye\w*|tazminat\w*|kira\w*)\b")
_CORRECTION = re.compile(r"\b(?:degil|duzelt\w*|pardon|hayir|yanlis|artik)\b")
_PREFIX_START = re.compile(r"\b(?:baslangic|baslama|ise giris|ise baslama|giris)(?: tarihi\w*)?\b")
_PREFIX_END = re.compile(r"\b(?:bitis|isten cikis|cikis|ayrilis)(?: tarihi\w*)?\b")
_AFTER_START = re.compile(r"\b(?:basladim|girdim|ise alindim)\b")
_AFTER_END = re.compile(r"\b(?:ciktim|cikarildim|ayrildim|sona erdi)\b")


def _fold(text: str) -> str:
    # Preserve offsets into the original text (no whitespace collapsing).
    return text.replace("İ", "i").lower().translate(str.maketrans("çğıöşüâ", "cgiosua"))


@dataclass(frozen=True, slots=True)
class FactRecord:
    field: str
    value: str
    question_index: int
    span_start: int
    span_end: int
    text: str

    def as_dict(self) -> dict:
        return {"field": self.field, "value": self.value, "origin": "user_statement",
                "question_index": self.question_index, "span": [self.span_start, self.span_end], "text": self.text}


@dataclass(frozen=True, slots=True)
class CalendarDuration:
    years: int
    months: int
    days: int
    total_days: int

    def as_dict(self) -> dict:
        return {"years": self.years, "months": self.months, "days": self.days,
                "total_days": self.total_days, "kind": "declared_date_calendar_arithmetic",
                "legal_service_determined": False}


@dataclass(frozen=True, slots=True)
class UserEventFacts:
    amount: Decimal | None = None
    gross: bool | None = None
    currency: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    duration: CalendarDuration | None = None
    records: tuple[FactRecord, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def prompt_records(self) -> list[dict]:
        """Only exact user facts + explicitly nonlegal deterministic derivation."""
        values = [record.as_dict() for record in self.records]
        if self.duration is not None:
            values.append({"field": "calendar_duration", "origin": "deterministic_user_date_arithmetic",
                           "value": self.duration.as_dict(),
                           "derived_from": ["employment_start", "employment_end"]})
        return values


def _record(field: str, value: str, index: int, original: str, start: int, end: int) -> FactRecord:
    return FactRecord(field, value, index, start, end, original[start:end])


def _calendar_duration(start: date, end: date) -> CalendarDuration | None:
    if end < start:
        return None
    def shifted(value: date, years: int = 0, months: int = 0) -> date:
        total = (value.year + years) * 12 + value.month - 1 + months
        year, zero_month = divmod(total, 12)
        month = zero_month + 1
        return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))
    years = end.year - start.year
    anniversary = shifted(start, years=years)
    if anniversary > end:
        years -= 1
        anniversary = shifted(start, years=years)
    months = (end.year - anniversary.year) * 12 + end.month - anniversary.month
    month_date = shifted(anniversary, months=months)
    if month_date > end:
        months -= 1
        month_date = shifted(anniversary, months=months)
    return CalendarDuration(years, months, (end - month_date).days, (end - start).days)


def _date_candidates(text: str) -> list[tuple[int, int, date | None]]:
    values = []
    for pattern in _DATES:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end, _ in values):
                continue
            try:
                month = _MONTHS.get(match["month"], 0) or int(match["month"])
                value = date(int(match["year"]), month, int(match["day"]))
            except (ValueError, OverflowError):
                value = None
            values.append((match.start(), match.end(), value))
    return sorted(values)


def _date_role(text: str, dates: list[tuple[int, int, date | None]], position: int) -> str | None:
    start, end, _ = dates[position]
    before_start = max(dates[position - 1][1] if position else 0, start - 65)
    after_end = min(dates[position + 1][0] if position + 1 < len(dates) else len(text), end + 65)
    before, after = text[before_start:start], text[end:after_end]
    choices = []
    for field, prefix, suffix in (("employment_start", _PREFIX_START, _AFTER_START),
                                   ("employment_end", _PREFIX_END, _AFTER_END)):
        for match in prefix.finditer(before):
            # A role label must actually introduce this date. In an all-in-one
            # word problem, "çıkış parası alırım, 50000 brüt ücret ..." is a
            # payment goal, not an end-date label for the next date encountered.
            if not re.fullmatch(r"[\s:;=,'’\"()\-–—]*(?:olarak\s*)?", before[match.end():]):
                continue
            choices.append((len(before) - match.end(), field))
        for match in suffix.finditer(after):
            choices.append((match.start(), field))
    if not choices:
        return None
    choices.sort()
    if len(choices) > 1 and choices[0][0] == choices[1][0] and choices[0][1] != choices[1][1]:
        return None
    return choices[0][1]


def _pay_candidates(original: str, text: str, dates: list[tuple[int, int, date | None]], index: int) -> list[tuple]:
    values = []
    for match in _AMOUNT.finditer(text):
        if any(match.start() < end and match.end() > start for start, end, _ in dates):
            continue
        left, right = max(0, match.start() - 35), min(len(text), match.end() + 35)
        surrounding = text[left:right]
        pay = list(_PAY.finditer(surrounding))
        if not pay:
            continue
        # A year after a salary discussion is not the salary itself.
        if not match["scale"] and not match["currency"] and re.match(r"\s*(?:yil|sene)", text[match.end():]):
            continue
        def distance(item):
            a, b = item.start() + left, item.end() + left
            return min(abs(match.start()-b), abs(a-match.end()))
        other = list(_OTHER_PAYMENT.finditer(surrounding))
        if other and min(distance(item) for item in other) < min(distance(item) for item in pay):
            continue
        try:
            number = match["number"]
            if "," in number or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", number):
                number = number.replace(".", "").replace(",", ".")
            amount = Decimal(number) * {None: 1, "bin": 1000, "milyon": 1000000}[match["scale"]]
        except (InvalidOperation, KeyError):
            continue
        if not amount.is_finite() or amount <= 0:
            values.append((None, None, None, None, None))
            continue
        bases = list(_BASIS.finditer(surrounding))
        basis = min(bases, key=distance) if bases else None
        gross = None if basis is None else basis.group() == "brut"
        if basis is not None and basis.group() == "brut" and re.search(r"brut\s+degil", surrounding):
            gross = False if re.search(r"\bnet\b", surrounding) else None
        currency = {"tl": "TRY", "try": "TRY", "lira": "TRY", "₺": "TRY", "eur": "EUR", "euro": "EUR",
                    "usd": "USD", "dolar": "USD"}.get(match["currency"])
        record = _record("pay_amount", str(amount), index, original, match.start(), match.end())
        basis_record = (_record("pay_basis", "gross" if gross else "net" if gross is False else "unspecified",
                                index, original, left + basis.start(), left + basis.end()) if basis is not None else None)
        values.append((amount, gross, currency, record, basis_record))
    return values


def collect_user_facts(question: str, prior_questions: Sequence[str] = (),
                       history: Sequence[HistoryTurn] = ()) -> UserEventFacts:
    """Collect declared values, not inferred or corpus/model-supplied facts.

    ``question_index`` is the zero-based position in the supplied previous user
    inputs plus the current question. Two unlabelled dates in one user message
    are treated as the declared ordered start/end pair, never sorted. Explicit
    date labels override order. Latest declarations/corrections override earlier
    values; invalid latest dates erase the old field rather than reusing it.
    Currency and gross/net basis remain unknown unless explicitly supplied.
    """
    previous = list(prior_questions) if prior_questions else [turn.question for turn in history]
    selected = user_inputs(question, history, prior_questions)
    offset = len(previous) + 1 - len(selected)
    records: dict[str, FactRecord] = {}
    amount, gross, currency = None, None, None
    start_date, end_date = None, None
    issues: list[str] = []
    for local_index, original in enumerate(selected):
        index, text = offset + local_index, _fold(original)
        dates = _date_candidates(text)
        pays = _pay_candidates(original, text, dates, index)
        if pays:
            # Same utterance can state both net and gross. Prefer its explicitly
            # gross value unless it is phrased as a correction; across turns,
            # the latest declaration always wins.
            chosen = pays[-1]
            if not _CORRECTION.search(text):
                chosen = next((pay for pay in reversed(pays) if pay[1] is True), chosen)
            amount, gross, currency, amount_record, basis_record = chosen
            records.pop("pay_amount", None)
            records.pop("pay_basis", None)
            if amount_record is None:
                issues.append("invalid_pay_amount")
            else:
                issues = [issue for issue in issues if issue != "invalid_pay_amount"]
                records["pay_amount"] = amount_record
            if basis_record:
                records["pay_basis"] = basis_record
        for position, (start, end, value) in enumerate(dates):
            field = _date_role(text, dates, position)
            if field is None and len(dates) == 2:
                field = "employment_start" if position == 0 else "employment_end"
            if field is None:
                issues.append("unassigned_date")
                continue
            if value is None:
                issues.append("invalid_" + field)
                records.pop(field, None)
            else:
                issues = [issue for issue in issues if issue != "invalid_" + field]
                records[field] = _record(field, value.isoformat(), index, original, start, end)
            if field == "employment_start":
                start_date = value
            else:
                end_date = value
    duration = None
    if start_date is not None and end_date is not None:
        if end_date < start_date:
            issues.append("reversed_employment_dates")
        else:
            duration = _calendar_duration(start_date, end_date)
    return UserEventFacts(amount, gross, currency, start_date, end_date, duration,
                          tuple(records.values()), tuple(dict.fromkeys(issues)))
