"""Exact numeric tokens and their units; never infer conversions or legal facts."""

import re

from api.ai.search_plan import normalize

# A hyphen immediately following a number is a range separator, not a minus
# sign: 01.03.2015-15.04.2023 must retain the second positive date token.
_NUMBER = re.compile(r"(?<!\d)[+\-]?\d+(?:[.,/]\d+)*")
_UNIT = re.compile(
    r"\s*(iş günü|gün|hafta|ay|yıl|sene|sen e|saat|dakika|tl|try|lira|türk lirası|eur|euro|usd|dolar|₺|€|\$)"
    r"(?=$|[^\w]|(?:lık|lik|luk|lük|dır|dir|dur|dür|da|de|dan|den|ın|in|un|ün|ı|i|u|ü)\b)"
)
_ALIASES = {"try": "tl", "lira": "tl", "türk lirası": "tl", "₺": "tl",
            "euro": "eur", "€": "eur", "dolar": "usd", "$": "usd", "sene": "yıl", "sen e": "yıl"}


_UNITS_WORDS = {"iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9}
_TENS_WORDS = {"on": 10, "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90}
_ONE = {"bir": 1}
_JOINED = re.compile(
    r"^(?:(bin))?(?:(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)?(yüz))?"
    r"(on|yirmi|otuz|kırk|elli|altmış|yetmiş|seksen|doksan)?(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)?$"
)
_WORD = re.compile(r"[a-zçğıöşü]+")
_HALF = re.compile(r"\b(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz)\s?buçuk")
# The verified PDF of İİK 67 contains the extracted unit "bir sen e içinde".
# Recognize this quantified unit only; do not alter stored/displayed evidence
# or generally join arbitrary words (in particular, 'senet' is not a duration).
_DURATION_AFTER = re.compile(r"\s+(?:iş günü|gün|hafta|ay|yıl|sene|sen e|saat|dakika)")
_DISTRIBUTIVE = {"birer": 1, "ikişer": 2, "üçer": 3, "dörder": 4, "beşer": 5,
                 "altışar": 6, "yedişer": 7, "sekizer": 8, "dokuzar": 9, "onar": 10}


def normalize_half_percentage(text: str) -> str:
    """Explicit 'yarısı/yarısını' is 50 percent, not an unquantified word.

    Apply to both evidence and claim, so a claim saying half cannot pass
    against an evidence-only 40 percent payment schedule.
    """
    text = re.sub(r"\byarısı(?:nı|na|nın|ndan)?\b", "%50", text)
    # Percent values often carry a possessive suffix: "yüzde ellisi".
    # Without stripping that suffix the number tokenizer sees no number at
    # all, allowing an incorrect "yüzde kırkı" to evade the numeric guard.
    names = {**_UNITS_WORDS, **_TENS_WORDS, "yüz": 100}
    pattern = r"\byüzde\s+(" + "|".join(sorted(names, key=len, reverse=True)) + r")(?:['’]?(?:s[ıi]|[ıi])(?:n[ıi]n|n[ıi]|na|ne|ndan|nden)?)\b"
    return re.sub(pattern, lambda match: f"%{names[match.group(1)]}", text)


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
    # "birbuçuk yıl" / "iki buçuk ay" -> 1,5 / 2,5 (bildirim süreleri tablosu: "birbuçuk yıldan üç yıla kadar").
    value = _HALF.sub(lambda m: f"{_UNITS_WORDS.get(m.group(1), 1)},5", value)
    out: list[str] = []
    position = 0
    words = list(_WORD.finditer(value))
    index = 0
    while index < len(words):
        match = words[index]
        number = _word_value(match.group())
        if match.group() in _DISTRIBUTIVE and _DURATION_AFTER.match(value, match.end()):
            number = _DISTRIBUTIVE[match.group()]
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
    # The statutes write "işgünü" (one word), a sentence writes "iş günü": the same unit (measured 2026-10-30: a correct
    # "on iş günü" sentence was refused against "on işgünü").
    value = spell_numbers(normalize_half_percentage(normalize(text)).replace("−", "-").replace("işgün", "iş gün"))
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
    # A Turkish predicate can govern two coordinated amounts: "idare
    # mahkemelerinde altmış ve vergi mahkemelerinde otuz gündür". Only
    # duration-unit sharing within this explicit locative coordination is
    # recognized; never propagate currencies, across sentences or past units.
    shared = re.compile(
        r"\b(\d+)\s+ve\s+(?:[a-zçğıöşü]+\s+){0,3}"
        r"[a-zçğıöşü]+(?:de|da|nde|nda)\s+(\d+)(?=\s)"
    )
    for match in shared.finditer(value):
        unit = _UNIT.match(value, match.end())
        if unit and unit.group(1) in {"gün", "hafta", "ay", "yıl", "saat", "dakika"}:
            typed.add((match.group(1), unit.group(1)))
    return numbers, typed


# "3 yıldan fazla" (3 dahil değil) ile "3 yıl ve üzeri" / "en az 3 yıl" (3 dahil) aynı sayıyı taşır, sayı kontrolü farkı görmez.
# Ölçüldü 2026-10-25: kanun "üç yıldan fazla sürmüş işçi için sekiz hafta" derken cevap "3 yıl ve üzeri için 8 hafta" yazdı ve
# denetçi onayladı; 3 yıl çalışan kişiye yanlış süre (doğrusu altı hafta) söylendi.
_N = r"(\d+(?:,\d+)?)"
_EXCLUSIVE = re.compile(_N + r"\s+[a-zçğıöşü]*?(?:dan|den|tan|ten)\s+(?:fazla|çok|uzun|büyük)\b")
_INCLUSIVE = re.compile(_N + r"\s+[a-zçğıöşü]+\s+(?:ve|veya|ya da)\s+(?:üzeri|üstü|daha fazla|daha çok|daha uzun)\b|\ben az\s+" + _N)
_AGE_LT = re.compile(_N + r"\s+(?:yaşını\s+doldurmamış|yaşından\s+küçük)\b")
_AGE_LE = re.compile(_N + r"\s+(?:(?:ve\s+)?(?:daha\s+)?küçük\s+yaş\w*|yaş(?:ında)?\s+ve\s+altı\w*)\b")


def _age_upper_bounds(text: str) -> tuple[set[str], set[str]]:
    value = spell_numbers(normalize(text))
    return ({m.group(1) for m in _AGE_LT.finditer(value)},
            {m.group(1) for m in _AGE_LE.finditer(value)})


def _bounds(text: str) -> tuple[set[str], set[str]]:
    value = spell_numbers(normalize(text))
    return ({m.group(1) for m in _EXCLUSIVE.finditer(value)},
            {m.group(1) or m.group(2) for m in _INCLUSIVE.finditer(value)})


def boundaries_supported(claim: str, source: str) -> bool:
    """A lower bound must keep the source's inclusiveness: "X'ten fazla" never becomes "X ve üzeri / en az X", nor the reverse."""
    claim_gt, claim_ge = _bounds(claim)
    source_gt, source_ge = _bounds(source)
    claim_lt, claim_le = _age_upper_bounds(claim)
    source_lt, source_le = _age_upper_bounds(source)
    return not ({n for n in claim_ge if n in source_gt and n not in source_ge}
                or {n for n in claim_gt if n in source_ge and n not in source_gt}
                or {n for n in claim_lt if n in source_le and n not in source_lt}
                or {n for n in claim_le if n in source_lt and n not in source_le})


_USER_YEARS = re.compile(r"(\d+(?:,\d+)?)\s*(?:yıl|yil|sene)")
_USER_MONTHS = re.compile(r"(\d+)\s*(?:ay)\b")


def user_duration_months(known: str) -> float | None:
    """The length of time the user states, in months: "3 yıl 2 ay" -> 38, "3,5 yıl" -> 42, "40 ay" -> 40. None if none is stated.

    Measured 2026-10-31: for "3 yıl 2 ay" the guidance below saw only the number 3, called it EQUAL to the "üç yıldan fazla"
    threshold and told the writer the six-week tier applies; the right tier for 38 months is the eight-week one.
    """
    if not known:
        return None
    value = spell_numbers(normalize(known))
    years = [float(item.replace(",", ".")) for item in _USER_YEARS.findall(value)]
    months = [int(item) for item in _USER_MONTHS.findall(value)]
    if not years and not months:
        return None
    return sum(years) * 12 + sum(months)


def _threshold_months(match: re.Match) -> float | None:
    """The threshold of an "X yıldan/aydan fazla" match in months; None for another unit."""
    word = match.group(0).split()[1] if len(match.group(0).split()) > 1 else ""
    number = float(match.group(1).replace(",", "."))
    if word.startswith(("yıl", "yil", "sene")):
        return number * 12
    if word.startswith("ay"):
        return number
    return None


def _threshold_relation(match: re.Match, known: str, user_numbers: set[str]) -> str | None:
    """'equal' / 'above' / 'below': where the user's stated duration sits against the threshold; 'equal' by bare number when no
    duration with a unit is stated (the earlier behaviour); None when the number is not the user's at all."""
    duration, limit = user_duration_months(known), _threshold_months(match)
    if duration is not None and limit is not None:
        if abs(duration - limit) < 1e-9:
            return "equal"
        return "above" if duration > limit else "below"
    return "equal" if match.group(1) in user_numbers else None


def user_threshold_notes(texts: list[str], known: str) -> list[str]:
    """Plain warnings for the writer: where the user's stated duration sits against a source's "X'ten fazla" threshold (guidance
    only, never evidence)."""
    user_numbers = _facts(known)[0] if known else set()
    notes: list[str] = []
    for text in texts:
        value = spell_numbers(normalize(text))
        for match in _EXCLUSIVE.finditer(value):
            relation = _threshold_relation(match, known, user_numbers) if known else None
            if relation == "equal":
                note = (f"Kullanıcının verdiği {match.group(1)} sayısı kaynaktaki \"{match.group(0)}\" eşiğine EŞİTTİR, onu aşmaz: "
                        "bu eşiğin açtığı üst dilim kullanıcıya uygulanmaz; \"kadar\" diyen önceki dilim uygulanır.")
            elif relation == "above":
                note = (f"Kullanıcının belirttiği süre kaynaktaki \"{match.group(0)}\" eşiğini AŞAR: bu eşiğin açtığı üst dilim "
                        "kullanıcıya uygulanır; \"kadar\" diyen önceki dilimler uygulanmaz.")
            else:
                continue
            if note not in notes:
                notes.append(note)
    return notes


def user_threshold_misapplied(claim: str, source: str, known: str) -> bool:
    """The user's own number sits exactly on a source's "X'ten fazla" threshold, and the claim applies that tier without saying so.

    Measured 2026-10-30: the user works "3 yıldır"; the notice-period rule gives eight weeks only to those who worked MORE than
    three years (six weeks up to and including three). An answer that says "sekiz haftalık bildirim süresi" for this user is
    wrong, and the model checker accepted it in one of two similar sentences. A claim that names the threshold itself
    ("üç yıldan fazla çalışanlar için sekiz hafta") is a general statement and stays allowed.
    """
    if not known:
        return False
    value = spell_numbers(normalize(source))
    user_numbers = _facts(known)[0]
    claim_values = _facts(claim)[1]
    claim_exclusive = _bounds(claim)[0]
    for match in _EXCLUSIVE.finditer(value):
        number = match.group(1)
        # Only a user ON the threshold is misserved by the upper tier; one who exceeds it (3 yıl 2 ay) is owed exactly that tier.
        if number in claim_exclusive or _threshold_relation(match, known, user_numbers) != "equal":
            continue
        # The tier this threshold opens: its own amounts, up to the next list separator ("... için sekiz hafta sonra,").
        tier = re.split(r"[;,.]", value[match.end():], maxsplit=1)[0]
        if _facts(tier)[1] & claim_values:
            return True
    return False


def same_numeric_scope(first: str, second: str) -> bool:
    """A semantic duplicate must not erase a distinct number, unit or bound."""
    return (_facts(first) == _facts(second) and _bounds(first) == _bounds(second)
            and _age_upper_bounds(first) == _age_upper_bounds(second))


def numeric_claims_supported(claim: str, source: str) -> bool:
    """All numbers, including small durations/rates, must match whole source tokens.

    A matching number with a different currency/duration/percentage is insufficient.
    This checks values and units, not who a number belongs to or semantic entailment.
    """
    numbers, typed = _facts(claim)
    known, known_typed = _facts(source)
    # Bir kararın künyesi tarihi "05.06.2014", esas numarasını "2014/5973" diye yazar; "2014 tarihli karar" demek yanlış sayı
    # değildir. Yalnız kaynak tarafına ekli yıl (19xx/20xx) kabul edilir; iddianın şartı değişmez.
    for token in list(known):
        year = re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]((?:19|20)\d{2})|((?:19|20)\d{2})/\d+", token)
        if year:
            known.add(year.group(1) or year.group(2))
    return numbers.issubset(known) and typed.issubset(known_typed)
