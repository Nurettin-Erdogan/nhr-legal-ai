"""Conservative query intent constraints, not a legal correctness classifier.

Topic groups are retrieval hints, never evidence or hard-coded legal answers.
All groups must match the actual passage, not just citation metadata. Unknown
questions retain lexical ranking and the model's explicit abstention contract.
"""
from dataclasses import dataclass
import re

from api.ai.search_plan import normalize


@dataclass(frozen=True)
class Intent:
    name: str
    groups: tuple[tuple[str, ...], ...]
    statute: tuple[str, str] | None = None


def question_intent(question: str) -> Intent | None:
    q = normalize(question)
    if 'kira' in q and any(t in q for t in ('tüfe', 'artış', 'zam', 'artır')):
        return Intent('rent_increase', (('kira',), ('tüfe', 'tüketici fiyat', 'artış', 'artır')),
                      ('6098', '344'))
    if 'kıdem' in q and 'tazminat' in q:
        return Intent('severance', (('kıdem tazminat',), ('işçi', 'hizmet ak', 'iş sözleş', 'fesih', 'feshed')),
                      ('1475', '14'))
    if 'itirazın iptal' in q:
        return Intent('objection_annulment', (('itirazın iptal',),), ('2004', '67'))
    if 'yıllık izin' in q and any(t in q for t in ('ispat', 'kanıt', 'yük')):
        return Intent('leave_proof', (('yıllık izin',), ('ispat yük', 'izin defter', 'imzalı')))
    if 'idari' in q and any(t in q for t in ('süre', 'kaç gün')):
        return Intent('administrative_deadline', (('idari', 'idare mahkeme', 'danıştay'),
                      ('süre', 'gün')), ('2577', '7'))
    if 'bireysel başvuru' in q:
        return Intent('constitutional_application', (('bireysel başvuru',),), ('6216', '47'))
    if 'ortak velayet' in q:
        if any(t in q for t in ('şart', 'koşul')):
            return Intent('joint_custody', (('ortak velayet',),
                          ('yarar', 'rıza', 'görüş', 'idrak', 'menfaat', 'uzlaş', 'istek', 'uyum')))
        return Intent('joint_custody', (('ortak velayet',),))
    return None


def passage_relevant(question: str, text: str) -> bool:
    """Reject known topic mismatches even when the source is genuine."""
    intent = question_intent(question)
    value = normalize(text)
    if intent and not all(any(re.search(r'(?<!\w)' + re.escape(term), value) for term in group) for group in intent.groups):
        return False
    if intent and intent.name == 'joint_custody' and any(t in normalize(question) for t in ('şart', 'koşul')):
        if not any(t in value for t in ('yarar', 'rıza', 'rızası', 'görüş', 'idrak', 'menfaat', 'uzlaş', 'istek', 'uyum')):
            return False
    q = normalize(question)
    # A duration is not an answer to a fee question (observed DeepSeek regression).
    if any(t in q for t in ('kaç lira', 'harcı ne kadar', 'harç tutarı')):
        return bool(re.search(r'\b(?:tl|lira|harç|harcı|ücret)', value))
    if intent is None:
        from api.ai.search_plan import plan_search
        words = [w for w in plan_search(question).text.split() if len(w) >= 4
                 and not w.isdigit() and w not in ('kanun', 'madde', 'sayılı', 'sayili')]
        if words:
            stems = set(w[:max(4, len(w)-2)] for w in words)
            return sum(w in value for w in stems) >= min(2, len(stems))
    return True


def context_relevant(question, context):
    from api.ai.source_support import _sentences
    # Retrieval may return a fragment (including a historical version). Only
    # generation requires complete sentences; don't lose valid search records.
    return any(passage_relevant(question, s) for s in _sentences(context.content, include_tail=True))


def relevant_contexts(question, contexts):
    return [c for c in contexts if context_relevant(question, c)]


def intent_tsquery(intent: Intent) -> str:
    # Let PostgreSQL's Turkish dictionary stem the words. Prefix expansion on
    # common terms fans out over millions of rows and is deliberately avoided.
    # These are Python prefix matches, NOT Turkish dictionary headwords.
    # Feeding "artır" to PostgreSQL stems it again to "ar", losing actual
    # increase passages and adding unrelated matches. Use complete forms for
    # SQL only; keep passage/citation relevance checks unchanged.
    sql_forms = {'artır': ('artırım', 'artırılması', 'artırma')}
    return ' & '.join('(' + ' | '.join(
        ' <-> '.join(word for word in form.split())
        for term in group for form in sql_forms.get(term, (term,))
    ) + ')' for group in intent.groups)


def focused_intent_tsquery(question: str, intent: Intent) -> str | None:
    """A statute-linked first pass, never evidence or an exhaustive search.

    Narrow deadline searches using the already mapped statute/article. There is
    deliberately no expected duration here (e.g. "one year"): such a hint would
    bias retrieval toward a predetermined legal answer.
    """
    from api.ai.passages import is_duration_question
    if not intent.statute or not is_duration_question(question):
        return None
    law, article = intent.statute
    if not law.isdigit() or not article.isdigit():
        return None
    return f'({intent_tsquery(intent)}) & {law} & {article}'


def semantic_search_text(question: str) -> str:
    """Query-only vocabulary expansion; not an answer or a change to stored vectors."""
    intent = question_intent(question)
    hints = {
        'rent_increase': 'kira bedelinin artırılması tüketici fiyat endeksi kira artışı',
        'leave_proof': 'yıllık izin kullanıldığının ispatı izin defteri imzalı belge işveren',
        'joint_custody': 'ortak velayet çocuğun üstün yararı ebeveynlerin görüşleri ortak velayet koşulları',
        'administrative_deadline': 'idari yargıda iptal davası açma süresi idare mahkemesi',
        'constitutional_application': 'Anayasa Mahkemesi bireysel başvuru süresi başvuru yollarının tüketilmesi',
    }
    hint = hints.get(intent.name, '') if intent else ''
    return f'{question}\nArama kavramları: {hint}' if hint else question
