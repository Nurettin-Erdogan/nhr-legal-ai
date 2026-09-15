from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str


class CorpusStats(BaseModel):
    source_count: int
    chunk_count: int
    decision_count: int
    legislation_count: int
    other_count: int = 0
    latest_decision_date: date | None


class LegalSearchHit(BaseModel):
    id: UUID
    source_type: str
    title: str
    source_url: str | None
    authority: str | None
    court_name: str | None
    chamber: str | None
    docket_no: str | None
    decision_no: str | None
    decision_date: date | None
    legislation_type: str | None
    law_name: str | None
    law_no: str | None
    article_no: str | None
    article_title: str | None
    official_gazette_date: date | None
    version_date: date | None
    effective_from: date | None
    effective_to: date | None
    source_version: str | None
    revision: int
    excerpt: str
    rank: float


class LegalSearchResponse(BaseModel):
    query: str
    as_of: date | None = None
    total: int
    limit: int
    offset: int
    results: list[LegalSearchHit]


class LegalChunk(BaseModel):
    id: UUID
    chunk_index: int
    content: str


class LegalSourceDetail(BaseModel):
    id: UUID
    source_type: str
    title: str
    source_url: str | None
    external_id: str | None
    authority: str | None
    court_name: str | None
    chamber: str | None
    docket_no: str | None
    decision_no: str | None
    decision_date: date | None
    legislation_type: str | None
    law_name: str | None
    law_no: str | None
    article_no: str | None
    article_title: str | None
    official_gazette_no: str | None
    official_gazette_date: date | None
    version_date: date | None
    effective_from: date | None
    effective_to: date | None
    canonical_source_name: str | None
    official_source_url: str | None
    ingestion_method: str | None
    fetched_at: datetime | None
    last_verified_at: datetime | None
    content_hash: str | None
    source_version: str | None
    revision: int
    is_current: bool
    superseded_by_id: UUID | None
    raw_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: list[LegalChunk]


class AIStatusResponse(BaseModel):
    provider: str
    model: str
    configured: bool
    embedding_model: str
    semantic_search_ready: bool


class AIAnswerRequest(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    conversation_id: UUID | None = None
    project_id: UUID | None = None
    as_of: date | None = None


class AICitation(BaseModel):
    marker: str
    source_id: UUID
    chunk_id: UUID
    source_type: str
    title: str
    reference: str
    source_url: str | None
    court_name: str | None = None
    chamber: str | None = None
    docket_no: str | None = None
    decision_no: str | None = None
    decision_date: date | None = None
    law_name: str | None = None
    law_no: str | None = None
    article_no: str | None = None
    page_number: int | None = None
    version_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source_version: str | None = None
    revision: int | None = None
    excerpt: str
    rank: float


class AIAnswerResponse(BaseModel):
    question: str
    as_of: date | None = None
    answer: str
    provider: str
    model: str
    citations: list[AICitation]
    grounded: bool
    unverified_markers: list[str] = Field(default_factory=list)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
