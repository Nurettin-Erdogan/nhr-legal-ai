"""Exact numeric tokens and their units; never infer conversions or legal facts."""

import re

from api.ai.search_plan import normalize

# A hyphen immediately following a number is a range separator, not a minus
# sign: 01.03.2015-15.04.2023 must retain the second positive date token.
_NUMBER = re.compile(r"(?<!\d)[+\-]?\d+(?:[.,/]\d+)*")
_UNIT = re.compile(
    r"\s*(iş günü|gün|hafta|ay|yıl|sene|tl|try|lira|türk lirası|eur|euro|usd|dolar|₺|€|\$)"
    r"(?=$|[^\w]|(?:lık|lik|luk|lük|dır|dir|dur|dür|da|de|dan|den|ın|in|un|ün|ı|i|u|ü)\b)"
)
_ALIASES = {"try": "tl", "lira": "tl", "türk lirası": "tl", "₺": "tl",
            "euro": "eur", "€": "eur", "dolar": "usd", "$": "usd", "sene": "yıl"}


_UNITS_WORDS = {"iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
_TENS_WORDS = {"on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90}
_ONE = {"bir": 1}
_JOINED = re.compile(
    r"^(?:(bin))?(?:(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)?(yüz))?"
    r"(on|yirmi|otuz|kırk|elli|altmış|yetmiş|seksen|doksan)?(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)?$"
)
_WORD = re.compile(r"[a-zçğıöşü]+")
_DURATION_AFTER = re.compile(r"\s+(?:iş günü|gün|hafta|ay|yıl|sene)")


def _word_value(word: str) -> int | None:
    """Tek sözcüklük Türkçe sayı ("beş", "oniki", "yüzyirmi"); "bir" yalnız birleşik sayının parçasıysa."""
    match = _JOINED.match(word)
    if not match or not word:
        return None
    thousand, hundred_count, hundred, tens, units = match.groups()
    if not any((thousand, hundred, tens, units)):
        return None
    if word == "bir":
        return None  # tek başına "bir" çoğu zaman belirtme sözcüğüdür; süre önündeyse ayrıca ele alınır
    value = 1000 if thousand else 0
    if hundred:
        value += 100 * ((_UNITS_WORDS.get(hundred_count) or _ONE.get(hundred_count) or 1) if hundred_count else 1)
    value += _TENS_WORDS.get(tens, 0) + (_UNITS_WORDS.get(units) or _ONE.get(units) or 0)
    return value


def spell_numbers(value: str) -> str:
    """Yazıyla sayıları rakama çevirir ("oniki aylık" -> "12 aylık", "beş yıl" -> "5 yıl", "on iki" -> "12").

    Kanun metinleri sayıları çoğu zaman yazıyla verir; model aynı sayıyı rakamla yazınca doğru cümle "kaynakta olmayan
    sayı" diye eleniyordu (canlıda: "oniki aylık TÜFE ortalaması", 2026-10-18). Her iki metne de aynı çeviri uygulanır.
    Tek başına "bir" yalnız bir sürenin önündeyse ("bir yıl") 1 sayılır.
    """
    out: list[str] = []
    position = 0
    words = list(_WORD.finditer(value))
    index = 0
    while index < len(words):
        match = words[index]
        number = _word_value(match.group())
        if number is None and match.group() == "bir" and _DURATION_AFTER.match(value, match.end()):
            number = 1
        if number is None:
            index += 1
            continue
        end = match.end()
        # Ayrı yazılmış birleşik sayı: "on iki", "yüz yirmi beş".
        while index + 1 < len(words) and value[end:words[index + 1].start()].strip() == "":
            following = _word_value(words[index + 1].group())
            if following is None or following >= number or (number % 10 and following < 10):
                break
            number += following
            index += 1
            end = words[index].end()
        out.append(value[position:match.start()])
        out.append(str(number))
        position = end
        index += 1
    out.append(value[position:])
    return "".join(out)


def _facts(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    value = spell_numbers(normalize(text).replace("−", "-"))
    numbers, typed = set(), set()
    for match in _NUMBER.finditer(value):
        number = match.group()
        numbers.add(number)
        before = value[max(0, match.start() - 16):match.start()]
        if re.search(r"(?:%|\byüzde)\s*$", before):
            typed.add((number, "%"))
        unit = _UNIT.match(value, match.end())
        if unit:
            name = unit.group(1)
            typed.add((number, _ALIASES.get(name, name)))
        prefix = re.search(r"([₺€$])\s*$", before)
        if prefix:
            typed.add((number, _ALIASES[prefix.group(1)]))
    return numbers, typed


def numeric_claims_supported(claim: str, source: str) -> bool:
    """All numbers, including small durations/rates, must match whole source tokens.

    A matching number with a different currency/duration/percentage is insufficient.
    This checks values and units, not who a number belongs to or semantic entailment.
    """
    numbers, typed = _facts(claim)
    known, known_typed = _facts(source)
    return numbers.issubset(known) and typed.issubset(known_typed)
