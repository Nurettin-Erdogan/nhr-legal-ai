from __future__ import annotations

from datetime import date
from uuid import UUID

from api.ai.rag import RAGContext


def court_decision_context(
    *,
    chunk_id: str = "00000000-0000-0000-0000-000000000001",
    source_id: str = "00000000-0000-0000-0000-000000000002",
    content: str = "İşçi, haklı nedenle fesih hâlinde kıdem tazminatına hak kazanır.",
    rank: float = 0.5,
) -> RAGContext:
    return RAGContext(
        chunk_id=UUID(chunk_id),
        source_id=UUID(source_id),
        source_type="court_decision",
        title="Yargıtay 9. Hukuk Dairesi kararı",
        source_url="https://example.test/decision/1",
        authority="Yargıtay",
        court_name="Yargıtay",
        chamber="9. Hukuk Dairesi",
        docket_no="2026/1",
        decision_no="2026/2",
        decision_date=date(2026, 1, 2),
        law_name=None,
        law_no=None,
        article_no=None,
        article_title=None,
        content=content,
        rank=rank,
    )


def legislation_context(
    *,
    chunk_id: str = "00000000-0000-0000-0000-000000000011",
    source_id: str = "00000000-0000-0000-0000-000000000012",
    content: str = "İşveren, iş sözleşmesini haklı nedenle derhal feshedebilir.",
    rank: float = 0.4,
) -> RAGContext:
    return RAGContext(
        chunk_id=UUID(chunk_id),
        source_id=UUID(source_id),
        source_type="legislation",
        title="İş Kanunu madde 25",
        source_url="https://example.test/law/4857/25",
        authority="Mevzuat Bilgi Sistemi",
        court_name=None,
        chamber=None,
        docket_no=None,
        decision_no=None,
        decision_date=None,
        law_name="İş Kanunu",
        law_no="4857",
        article_no="25",
        article_title="İşverenin haklı nedenle derhal fesih hakkı",
        content=content,
        rank=rank,
    )


def document_context(
    *,
    chunk_id: str = "00000000-0000-0000-0000-000000000021",
    document_id: str = "00000000-0000-0000-0000-000000000022",
    content: str = "Müvekkilin iş sözleşmesi 15 Ocak 2026 tarihinde feshedilmiştir.",
    rank: float = 0.6,
) -> RAGContext:
    return RAGContext(
        chunk_id=UUID(chunk_id),
        source_id=UUID(document_id),
        source_type="document",
        title="iş_sözleşmesi.pdf",
        source_url=None,
        authority="Kullanıcı belgesi",
        court_name=None,
        chamber=None,
        docket_no=None,
        decision_no=None,
        decision_date=None,
        law_name=None,
        law_no=None,
        article_no=None,
        article_title="Fesih",
        content=content,
        rank=rank,
        page_number=3,
    )
