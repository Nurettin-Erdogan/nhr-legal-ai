"""Compose independently checked legal text with provable user-input context.

User statements and calendar arithmetic are explicitly not official law. They
never enter the quote/number evidence used to verify a legal claim. Temporal
coverage is checked from source metadata, not guessed by a language model.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from api.ai.dialogue import personal_outcome_topic
from api.ai.rag import HistoryTurn, RAGContext
from api.ai.trust import usable_as_evidence
from api.ai.user_facts import UserEventFacts, collect_user_facts


@dataclass(frozen=True, slots=True)
class EventContext:
    facts: UserEventFacts
    applicable_on: date | None
    historical_basis_missing: bool
    applicability_verified: bool = False

    @property
    def payload(self) -> dict:
        return {"user_facts_not_law": self.facts.prompt_records,
                "requested_event_date": self.applicable_on.isoformat() if self.applicable_on else None,
                "historical_applicability_verified": self.applicability_verified,
                "temporal_status": "verified_interval" if self.applicability_verified else "unverified_event_scope",
                "legal_answer_scope": "current_reference_only" if self.historical_basis_missing else "supported_rules_only",
                "final_payment_calculated": False}


def source_covers_date(context: RAGContext, target: date) -> bool:
    if not usable_as_evidence(context):
        return False
    if context.source_type == "court_decision":
        return bool(context.decision_date is not None and context.decision_date <= target)
    if context.source_type != "legislation":
        return False
    # Neither a collection/version date nor is_current proves past effectiveness.
    return bool(context.effective_from is not None and context.effective_from <= target
                and (context.effective_to is None or context.effective_to >= target))


def build_event_context(question: str, contexts: Sequence[RAGContext], *,
                        prior_questions: Sequence[str] = (), history: Sequence[HistoryTurn] = (),
                        as_of: date | None = None, today: date | None = None) -> EventContext | None:
    if personal_outcome_topic(question, history, prior_questions) != "employment":
        return None
    if any(c.source_type == "document" for c in contexts):
        return None  # selected/private document evidence has its own factual reader
    facts = collect_user_facts(question, prior_questions, history)
    if facts.amount is None or facts.duration is None or facts.issues:
        return None
    target = as_of if as_of is not None else facts.end_date
    legal = [c for c in contexts if c.source_type != "document" and usable_as_evidence(c)]
    statutes = [c for c in legal if c.source_type == "legislation"]
    # At least every supplied candidate provision must be temporally admissible
    # before any of it can support an event-specific historical conclusion.
    verified = bool(target is not None and statutes and all(source_covers_date(c, target) for c in legal))
    missing = bool(target is not None and not verified)
    return EventContext(facts, target, missing, verified)


def _number(amount: Decimal) -> str:
    return format(amount, ",.2f").rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")


def event_summary(context: EventContext) -> str:
    facts, duration = context.facts, context.facts.duration
    assert facts.start_date and facts.end_date and duration and facts.amount is not None
    basis = "brüt " if facts.gross is True else "net " if facts.gross is False else ""
    currency = {"TRY": " TL", "EUR": " EUR", "USD": " USD"}.get(facts.currency, "")
    pieces = [f"{value} {label}" for value, label in ((duration.years, "yıl"), (duration.months, "ay"), (duration.days, "gün")) if value]
    interval = " ".join(pieces) or "0 gün"
    return (f"Verdiğiniz tarihler {facts.start_date:%d.%m.%Y}–{facts.end_date:%d.%m.%Y}; "
            f"aradaki takvim farkı {interval}. Bildirdiğiniz {basis}ücret {_number(facts.amount)}{currency}.")


def historical_gap(context: EventContext) -> str:
    assert context.applicable_on
    return (f"İstenen değerlendirme tarihi {context.applicable_on:%d.%m.%Y} için uygulanabilecek "
            "mevzuat sürümü ve döneme ait hesap sınırları getirilen kaynaklarla doğrulanmış değil. "
            "Bu yüzden güncel metinleri o tarihte geçerliymiş gibi kullanıp toplam ödeme tutarı çıkarmıyorum.")


def compose_event_answer(text: str, context: EventContext, *, legal_reference: bool = False,
                         generation_failed: bool = False) -> str:
    parts = [event_summary(context)]
    if context.historical_basis_missing:
        parts.append(historical_gap(context))
        if legal_reference:
            parts.append("Elimizdeki mevcut madde sürümlerinin söylediği ise şu; bu açıklama yukarıdaki tarih için kesin bir hak veya tutar tespiti değildir:")
    if generation_failed:
        if not context.historical_basis_missing:
            parts.append("Bu veriler korundu; fakat toplam ödeme için uygulanacak kural ve hesap parametrelerini henüz güvenilir biçimde doğrulayamadım.")
    elif text and (legal_reference or not context.historical_basis_missing):
        parts.append(text)
    return "\n\n".join(parts)
