"""Publication policy: unverified public-corpus records are candidates, not evidence."""

from api.ai.rag import RAGContext


def usable_as_evidence(context: RAGContext) -> bool:
    # User documents remain private document evidence, not official legal sources.
    return context.verification == 'official' or (
        context.source_type == 'document' and context.verification == 'user_document'
    )


def verified_contexts(contexts: list[RAGContext]) -> list[RAGContext]:
    return [context for context in contexts if usable_as_evidence(context)]
