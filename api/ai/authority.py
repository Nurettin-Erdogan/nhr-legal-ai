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
    intent = question_intent(question)
    reference = (laws[0], articles[0]) if laws and articles else (intent.statute if intent else None)
    if reference is None:
        return set()
    return {i for i, c in enumerate(contexts, 1)
            if c.source_type == 'legislation' and c.verification == 'official'
            and (c.law_no, c.article_no) == reference}


def answer_uses_primary_basis(question, cited_contexts, available_contexts):
    markers = primary_legislation_markers(question, available_contexts)
    if not markers:
        return True
    primary_ids = {available_contexts[i-1].chunk_id for i in markers}
    # Kullanıcı belgesine atıf mevzuat dayanağının yerine geçmez ama onu da bozmaz.
    return bool(cited_contexts) and all(
        c.chunk_id in primary_ids or c.source_type == 'document' for c in cited_contexts
    )
