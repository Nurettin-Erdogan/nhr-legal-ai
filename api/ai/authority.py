"""Separate source authenticity from authority for a general statutory answer.

An authentic decision may quote an older rule or concern a special legal regime.
When retrieval supplies the relevant official provision, a general rule answer
uses that provision, not a free-standing rule copied from a decision. Decisions
remain searchable and available for explicit case-law questions. This policy is
not a general legal-conflict detector or a guarantee that corpus metadata is right.
"""
from api.ai.relevance import case_law_requested, question_intent


def primary_legislation_markers(question, contexts):
    if case_law_requested(question):
        return set()
    # Lazy import avoids the retrieval -> relevance -> rag import cycle.
    from api.ai.retrieval import question_law_numbers, question_article_numbers
    laws, articles = question_law_numbers(question), question_article_numbers(question)
    if laws and articles:
        # "4857 m. 18 ve m. 20" iki açık kaynağa ihtiyaç duyar. Eskiden
        # yalnız ilk maddeye kilitlenip diğerini kanıttan siliyorduk.
        # Birden fazla kanun açıkça yazılmışsa hangi maddenin hangi kanuna
        # ait olduğunu burada güvenle çıkaramayız; yanlış eşleme dayatmayız.
        if len(set(laws)) != 1:
            return set()
        references = {(laws[0], article) for article in articles}
    else:
        intent = question_intent(question)
        if intent is None or intent.statute is None:
            return set()
        references = {intent.statute}
    return {i for i, c in enumerate(contexts, 1)
            if c.source_type == 'legislation' and c.verification == 'official'
            and (c.law_no, c.article_no) in references}


def answer_uses_primary_basis(question, cited_contexts, available_contexts):
    markers = primary_legislation_markers(question, available_contexts)
    if not markers:
        return True
    primary_ids = {available_contexts[i-1].chunk_id for i in markers}
    # Kullanıcı belgesine atıf mevzuat dayanağının yerine geçmez ama onu da bozmaz.
    return bool(cited_contexts) and all(
        c.chunk_id in primary_ids or c.source_type == 'document' for c in cited_contexts
    )


def topic_statute_terms(question, contexts):
    """Sorunun konusunu düzenleyen maddeler: işaret → o maddenin konu sözcükleri (`api.statute_hints`).

    Kanun cümlesi çoğu zaman sorunun sözcüklerini taşımaz: "haksız fesihte hangi tazminat istenir?" sorusunun cevabı
    olan "Bildirim şartına uymayan taraf … tazminat ödemek zorundadır" cümlesinde ne "haksız" ne "fesih" geçer. Sözcük
    örtüşmesine bakan alaka süzgeci bu cümleyi eliyor, cevap yalnız mahkeme kararlarına dayanıyordu (ölçüldü: 2026-10-08).
    Burada yeni bir güven kaynağı yoktur: madde numarası elle doğrulanmış sabit tablodan, metin resmî doğrulanmış
    korpustan gelir; cümle yine aynen alıntılanır ve kaynak-destek denetiminden geçer. İçtihat isteyen soruda uygulanmaz.
    """
    if case_law_requested(question):
        return {}
    from api import statute_hints
    wanted = {(hint.law_no, hint.article_no): hint.expect for hint in statute_hints.suggest(question)}
    if not wanted:
        return {}
    return {
        marker: wanted[(context.law_no, context.article_no)]
        for marker, context in enumerate(contexts, 1)
        if context.source_type == 'legislation' and context.verification == 'official'
        and (context.law_no, context.article_no) in wanted
    }


def on_statute_topic(text, terms):
    """Cümle, maddenin konu sözcüklerinden birini taşıyor mu (maddenin başka konudaki fıkraları aday olmaz)."""
    from api.ai.search_plan import normalize
    value = normalize(text)
    return any(normalize(term) in value for term in terms)
