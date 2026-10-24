"""Neutral input collection, never legal advice or a source of legal facts.

These controls ask for facts about the user's own event. They do not encode an
entitlement, deadline, percentage or calculation formula. A clear personal
outcome request can collect user facts before retrieval; a scoped document
question stays with the source-bound reader. When used after retrieval, relevant
verified legislation is required unless the caller explicitly selects the
source-free, neutral-control mode.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from api.ai.rag import HistoryTurn, RAGContext
from api.ai.trust import usable_as_evidence


def _norm(text: str) -> str:
    return " ".join(text.replace("İ", "i").lower().translate(str.maketrans("çğıöşüâ", "cgiosua")).split())


_TOPICS = {
    "employment": re.compile(r"\b(?:isc\w*|isveren\w*|isyer\w*|isten|calis\w*|kidem\w*|ihbar\w*|maas\w*)\b"),
    "rent": re.compile(r"\b(?:kira\w*|kiraci\w*|ev\s+sahib\w*)\b"),
    "family": re.compile(r"\b(?:bosan\w*|velayet\w*|nafaka\w*|evlilik\w*)\b"),
    "damage": re.compile(r"\b(?:haksiz fiil|kaza\w*|zarar\w*)\b"),
    "enforcement": re.compile(r"\b(?:icra\w*|haciz\w*|odeme emr\w*)\b"),
}
_PERSONAL = re.compile(
    r"\b(?:ben|benim|bana|calistim|cikarildim|cikardilar|cikarildik|kovuldum|atildim|maasim\w*|ucretim\w*|"
    r"alirim|alabilirim|alcam|alacagim|odeyecegim|oderim|kiram\w*|yaparim|yapabilirim|aliom|aliyom|aliyorum)\b"
)
_OUTCOME = re.compile(r"ne kadar|\bkac\b|\bhesapla\w*|\btutar\w*|toplu para|\bkac\w* yapabil")
_GENERAL = re.compile(r"genel olarak|\bnedir\b|\bnelerdir\b|nasil hesaplanir|nasil belirlenir|sartlari|kosullari")
_DOCUMENT = re.compile(r"\b(?:belge\w*|dosya\w*|rapor\w*|karardaki|sozlesmedeki)\b")
_NEW_EVENT = re.compile(r"baska (?:bir )?(?:konu|olay|dosya|isci)|yeni (?:bir )?(?:soru|olay|konu)|oncekini unut")
_UNKNOWN = re.compile(r"bilmiyorum|hatirlamiyorum|paylasmak istemiyorum|soylemek istemiyorum|bende yok")
_DATE = re.compile(
    r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d{2}\b|"
    r"\b(?:\d{1,2}\s+)?(?:ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)\s+(?:19|20)\d{2}\b"
)
_MONEY = re.compile(r"\d[\d.,]*\s*(?:bin|milyon|tl|lira|₺)\b|\b\d{4,7}\b")
_REASON = re.compile(
    r"gerekce (?:gosterilmedi\w*|bildirilmedi\w*|gostermeden)|sebep (?:gosterilmedi\w*|bildirilmedi\w*)|sebepsiz|nedensiz|"
    r"istifa ettim|emekli oldum|askerlik|isyer\w* kapandi|kuculme|performans|devamsizlik|"
    r"gerekce(?:si| olarak)|nedeni(?:yle| olarak)|sebebi(?:yle| olarak)"
)


@dataclass(frozen=True, slots=True)
class InputPlan:
    topic: str
    missing: tuple[str, ...]
    question: str


def user_inputs(question: str, history: Sequence[HistoryTurn] = (),
                prior_questions: Sequence[str] = ()) -> tuple[str, ...]:
    """User statements only; assistant replies and corpus examples are never facts.

    Keep a bounded recent dialogue, stopping at an explicit event/topic change.
    This is context for understanding, not admissible legal evidence.
    """
    previous = list(prior_questions) if prior_questions else [turn.question for turn in history]
    values = [*previous[-8:], question]
    start = 0
    last_topic: str | None = None
    for index, text in enumerate(values):
        normalized = _norm(text)
        topics = [name for name, pattern in _TOPICS.items() if pattern.search(normalized)]
        if _NEW_EVENT.search(normalized):
            start = index
        if len(topics) == 1:
            if last_topic is not None and topics[0] != last_topic:
                start = index
            last_topic = topics[0]
    return tuple(values[start:])


def missing_input_plan(question: str, contexts: Sequence[RAGContext], *,
                       history: Sequence[HistoryTurn] = (),
                       prior_questions: Sequence[str] = (),
                       allow_source_free: bool = False) -> InputPlan | None:
    """Return only server-owned, non-normative questions for clear missing inputs.

    No plan for general rules, document reading, unavailable official data, or an
    unsupported topic. In particular, a source's example salary/date cannot fill
    a user field, and the user is never asked to supply a legal rule or TÜFE cap.
    """
    current = _norm(question)
    if _GENERAL.search(current) or _DOCUMENT.search(current) or _UNKNOWN.search(current):
        return None
    inputs = user_inputs(question, history, prior_questions)
    requests = [text for text in inputs if _PERSONAL.search(_norm(text)) and _OUTCOME.search(_norm(text))]
    if not requests:
        return None
    anchor = _norm(requests[-1])
    topics = [name for name, pattern in _TOPICS.items() if pattern.search(anchor)]
    if len(topics) != 1 or topics[0] not in {"employment", "rent"}:
        return None
    # A new substantive question is not an answer to an earlier input control.
    if question != requests[-1] and ("?" in question or re.search(r"\b(?:hangi|neden|nasil)\b", current)):
        if not _PERSONAL.search(current) or not _OUTCOME.search(current):
            return None
    source = _norm(" ".join(c.content for c in contexts
                            if c.source_type == "legislation" and usable_as_evidence(c)))
    facts = _norm(" ".join(inputs))
    if topics[0] == "employment":
        if not allow_source_free and (not _TOPICS["employment"].search(source) or not re.search(r"ucret|tazminat", source)):
            return None
        missing = []
        # A net or unlabelled amount must not silently become gross pay.
        pay_statements = [_norm(text) for text in inputs
                          if _MONEY.search(_norm(text)) and re.search(r"brut|\bnet\b|maas|ucret", _norm(text))]
        latest_pay = pay_statements[-1] if pay_statements else ""
        gross_known = bool(latest_pay and "brut" in latest_pay
                           and not re.search(r"brut\s+(?:degil|olmayan|olmadig)|\bnet\b", latest_pay))
        if not gross_known:
            missing.append(("gross_pay", "son brüt ücretinizi"))
        if len(_DATE.findall(facts)) < 2:
            missing.append(("employment_dates", "işe giriş ve işten çıkış tarihlerinizi"))
        if not _REASON.search(facts):
            missing.append(("termination_reason", "işten ayrılma nedeninizi"))
    else:
        if not allow_source_free and (not _TOPICS["rent"].search(source) or not re.search(r"artis|tuketici fiyat", source)):
            return None
        # Default/eviction questions must not turn into a rent-increase form.
        if not re.search(r"zam|artis|kac.*yap|kira\w*.*hesap", anchor):
            return None
        from api.ai.practical_answer import _amounts
        from api.ai.practical_answer import has_calculation_inputs, _LEGAL_LIMIT
        if has_calculation_inputs(question, inputs[:-1]) and not _LEGAL_LIMIT.search(question):
            return None  # explicit user arithmetic does not need a renewal date
        missing = []
        if not any(_amounts(text) for text in inputs):
            missing.append(("rent_amount", "mevcut kira tutarını"))
        if not (_DATE.search(facts) or (re.search(r"(?:19|20)\d{2}", facts)
                                      and re.search(r"ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik", facts))):
            missing.append(("renewal_period", "kiranın yenileneceği ay ve yılı"))
        if not re.search(r"\b(?:konut|ev|daire|catili|isyeri|is yeri|dukkan)\b", facts):
            missing.append(("property_type", "konut mu yoksa işyeri mi olduğunu"))
    if not missing:
        return None
    labels = [label for _, label in missing]
    fields = labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " ve " + labels[-1]
    first = "İ" if fields[0] == "i" else fields[0].upper()
    return InputPlan(topics[0], tuple(key for key, _ in missing), f"{first + fields[1:]} paylaşır mısınız?")


def resume_question(question: str, history: Sequence[HistoryTurn],
                    prior_questions: Sequence[str] = ()) -> str | None:
    """Continue a server-tagged input exchange without an extra rewrite call.

    The search string consists solely of original user text; nothing is inferred
    from assistant prose. New questions/topics always remain independent.
    """
    if not history or history[-1].answer_kind != "clarification":
        return None
    current = _norm(question)
    if "?" in question or _GENERAL.search(current) or _NEW_EVENT.search(current):
        return None
    if re.search(r"\b(?:hangi|neden|nasil|nedir|kac|ne kadar)\b", current):
        return None
    inputs = user_inputs(question, history, prior_questions)
    if len(inputs) < 2:
        return None
    # A clarification is not limited to an amount/compensation request.
    # "İşe iade şartları ve süresi?" -> clarification -> "dün" must retain
    # the *whole* original user question, not search for the word "dün".
    # For a second clarification, find the last substantive earlier user
    # question rather than reusing the previous one-word reply.
    anchor = next(
        (previous for previous in reversed(inputs[:-1])
         if ("?" in previous or len(_norm(previous).split()) >= 5)
         and len(_norm(previous).split()) >= 3),
        None,
    )
    if anchor is None:
        return None
    return f"{anchor.rstrip(' ?.')} — {question}"


def personal_outcome_topic(question: str, history: Sequence[HistoryTurn] = (),
                           prior_questions: Sequence[str] = ()) -> str | None:
    """The user's active goal, independent from the last short factual reply."""
    if _GENERAL.search(_norm(question)) or _DOCUMENT.search(_norm(question)):
        return None
    for previous in reversed(user_inputs(question, history, prior_questions)):
        text = _norm(previous)
        if _PERSONAL.search(text) and _OUTCOME.search(text):
            topics = [name for name, pattern in _TOPICS.items() if pattern.search(text)]
            return topics[0] if len(topics) == 1 else None
    return None


def outcome_search_query(question: str, history: Sequence[HistoryTurn] = (),
                         prior_questions: Sequence[str] = ()) -> str | None:
    """Expand a word problem's topic; NEVER feed salary/date digits as law IDs.

    These concepts select candidates, not entitlement or a legal conclusion.
    Explicit statute/case references retain the normal exact-reference path.
    Full event statements travel separately in typed user-fact records.
    """
    text = " ".join(user_inputs(question, history, prior_questions))
    if re.search(r"\b(?:kanun|madde|maddesi|TBK|HMK|İİK|İş K\.|E\.|K\.)", text, re.I):
        return None
    if personal_outcome_topic(question, history, prior_questions) == "employment":
        return "İşten çıkarılan işçinin kıdem tazminatı ve ihbar tazminatı hesaplama koşulları"
    return None
