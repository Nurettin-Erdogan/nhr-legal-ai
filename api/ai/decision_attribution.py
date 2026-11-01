"""Prevent a decision's catalogue court from laundering nested speakers.

This is a conservative section guard, not a complete judgment parser. Unknown
sections retain the independent semantic check; known lower-court/party text
cannot establish the catalogue court's own holding.
"""
import re

from api.ai.search_plan import normalize
from api.ai.source_support import _normalize

_SECTIONS = re.compile(
    r"İLK DERECE MAHKEMES[İI](?:N[İI]N)?(?:\s+KARARI|\s+GEREKÇES[İI])"
    r"|BÖLGE ADL[İI]YE MAHKEMES[İI](?:N[İI]N)?(?:\s+KARARI|\s+GEREKÇES[İI])"
    r"|DAVACI(?:NIN)?(?:\s+[İI]DD[İI]A(?:SI|LARI)|\s+TALE(?:B[İI]|PLER[İI]))"
    r"|DAVALI(?:NIN)?\s+SAVUNMA(?:SI|LARI)"
    r"|TEMY[İI]Z [İI]NCELEMES[İI]|YARGITAY(?:IN|’IN|'IN)?\s+(?:GEREKÇES[İI]|DEĞERLEND[İI]RMES[İI])"
    r"|HUKUK[İI] DEĞERLEND[İI]RME|GEREKÇE VE SONUÇ|SONUÇ VE KARAR"
)
_NESTED = re.compile(r"ilk derece|bölge adliye|davac[ıi]|daval[ıi]")
_HOLDING = re.compile(r"hükmet\w*|karar ver\w*|kararına göre|kararları?na göre|"
                      r"benimse\w*|kabul et\w*|belirt\w*|vurgula\w*|içtihad\w*|içtihat\w*|görüş\w*")


def decision_section_priority(context, question: str = '') -> int:
    """Ranking hint only: review (0), unknown (1), lower court (2), party (3).

    Never promotes trust or declares a claim true. An explicit section is used
    only for its own span; relevant reasoning later in a mixed chunk must not
    be hidden by an earlier party heading. Unlabelled text stays unknown.
    """
    if context.source_type != 'court_decision':
        return 1
    from api.ai.relevance import passage_relevant
    matches = list(_SECTIONS.finditer(context.content))
    priorities = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(context.content)
        body = context.content[match.end():end].strip(' :\n\t-')
        if not body or (question and not passage_relevant(question, body)):
            continue
        section = normalize(match.group())
        priorities.append(3 if re.search(r'davac[ıi]|daval[ıi]', section)
                          else 2 if _NESTED.search(section) else 0)
    return min(priorities, default=1)


def decision_selection_key(context, question: str):
    """Actual topic before section labels or retrieval rank; stable on ties.

    A genuine but unrelated court holding must not outrank a topic-relevant
    unlabelled passage just because it says 'HUKUKİ DEĞERLENDİRME'. Unknown
    relevance is demoted, not erased; the independent checker still decides
    whether the selected text supports a legal claim.
    """
    from api.ai.relevance import context_relevant
    from api.ai.retrieval import _hit_quality_score
    return (not context_relevant(question, context),
            decision_section_priority(context, question), -_hit_quality_score(question, context))


_REQUESTED_COURTS = (
    (re.compile(r"\byargıtay\b", re.I), "yargıtay"),
    (re.compile(r"\bdanıştay\b", re.I), "danıştay"),
    (re.compile(r"\bsayıştay\b", re.I), "sayıştay"),
    (re.compile(r"\b(?:aym|anayasa mahkemesi)\b", re.I), "anayasa mahkemesi"),
    (re.compile(r"\bkdk\b", re.I), "kamu denetçiliği kurumu"),
)


def decision_matches_question(question: str, context) -> bool:
    """Reject explicit cross-regime decisions, without asserting legal support.

    A matching court name or generic 'yetki/işçi/dava' words do not establish
    that a criminal jurisdiction dispute answers an employment-rights query.
    Mixed employment/criminal questions retain criminal evidence for checking.
    """
    if context.source_type != 'court_decision':
        return True
    q = normalize(question)
    employment = bool(re.search(r'işe iade|iş güvencesi|kıdem|ihbar|iş sözleş|işten çıkar|işçi|işveren', q))
    criminal_asked = bool(re.search(r'ceza|suç|savcı|sanık|mahkûm|mahkum|beraat|soruşturma|kovuşturma', q))
    if employment and not criminal_asked:
        metadata = normalize(' '.join(filter(None, (context.court_name, context.chamber, context.title))))
        if re.search(r'ceza daire|ceza genel kurul|ceza mahkeme|ağır ceza', metadata):
            return False
        from api.ai.relevance import case_law_requested
        if 'işe iade' in q and case_law_requested(question) and not re.search(
                r'işe iade|feshin geçersiz|iş güvencesi|otuz işçi|30 işçi', normalize(context.content)):
            return False
    return True


def requested_court_evidence(question: str, contexts):
    """When a user names a court, do not let another court's decision answer for it.

    Statutes and other non-decision evidence are preserved. Unspecified court
    searches keep their existing behavior; this is only a scope constraint for
    an explicit court request, not a general relevance or trust judgment.
    """
    from api.ai.search_plan import normalize

    contexts = [context for context in contexts if decision_matches_question(question, context)]
    requested = {name for pattern, name in _REQUESTED_COURTS if pattern.search(normalize(question))}
    if not requested:
        return list(contexts)
    kept = []
    for context in contexts:
        if context.source_type != "court_decision":
            kept.append(context)
            continue
        court = normalize(context.court_name or "")
        if any(name in court for name in requested):
            kept.append(context)
    return kept


def nested_evidence(context, quote: str) -> bool:
    if context.source_type != "court_decision":
        return False
    body, target = normalize(_normalize(context.content)), normalize(_normalize(quote))
    position = body.find(target)
    if position < 0:
        return True  # unknown position cannot clear an explicit court attribution
    section = None
    for match in _SECTIONS.finditer(context.content):
        # Normalization is not assumed length-preserving (whitespace/case).
        if len(normalize(_normalize(context.content[:match.start()]))) > position:
            break
        section = normalize(match.group())
    return bool(section and _NESTED.search(section))


def court_holding_misattributed(text: str, evidence, contexts) -> bool:
    claim = normalize(text)
    if not _HOLDING.search(claim):
        return False
    named = []
    for index, _ in evidence:
        context = contexts[index - 1]
        court = normalize(context.court_name or "")
        if context.source_type == "court_decision" and court and court in claim:
            named.append(index)
    if not named:
        return False
    # A real same-court holding may independently support the claim. A lower
    # court quotation from another record must not erase that valid evidence.
    return all(nested_evidence(contexts[index - 1], quote)
               for index, quote in evidence if index in named)


def irrelevant_case_filler(text: str, question: str) -> bool:
    """Drop a case anecdote that explicitly says it does not address the issue.

    Not a semantic relevance guarantee. Users asking whether a particular case
    is relevant, or for differences between cases, need precisely this analysis.
    """
    q, value = normalize(question), normalize(text)
    if re.search(r'karar\w*.*(?:ilgili mi|uygun mu|uygulanabilir mi|fark|karşılaştır|kıyas)|'
                 r'(?:karşılaştır|kıyas|fark).*karar', q):
        return False
    if not re.search(r'\b(?:bu|anılan|söz konusu) karar\b', value):
        return False
    return bool(re.search(r'ele alm(?:ıyor|amaktadır|az)|değerlendirme içerm(?:ez|iyor|emektedir)|'
                          r'(?:soruyla|konuyla|meseleyle) ilgili değil', value))


def with_case_identity(text: str, evidence, contexts) -> str:
    """Display known E./K. metadata for an unambiguous named-court claim.

    Runs only on approved prose. Appends identity, never a new legal claim;
    missing metadata, multiple decisions and anonymous reasoning are untouched.
    """
    value = normalize(text)
    cases = {}
    for index, _quote in evidence:
        context = contexts[index - 1]
        if (context.source_type == 'court_decision' and context.verification == 'official'
                and context.court_name and normalize(context.court_name) in value):
            cases[context.source_id] = context
    if len(cases) != 1:
        return text
    case = next(iter(cases.values()))
    if not case.docket_no or not case.decision_no:
        return text
    # Do not repeat full identity already written by the model.
    if case.docket_no in text and case.decision_no in text:
        return text
    return text.rstrip() + f' (E. {case.docket_no}, K. {case.decision_no})'
