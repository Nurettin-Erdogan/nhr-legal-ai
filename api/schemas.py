from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str


class CorpusStats(BaseModel):
    source_count: int
    chunk_count: int
    latest_decision_date: date | None


class LegalSearchHit(BaseModel):
    id: UUID
    title: str
    source_url: str | None
    chamber: str | None
    docket_no: str | None
    decision_no: str | None
    decision_date: date | None
    excerpt: str
    rank: float


class LegalSearchResponse(BaseModel):
    query: str
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
    title: str
    source_url: str | None
    external_id: str | None
    authority: str | None
    chamber: str | None
    docket_no: str | None
    decision_no: str | None
    decision_date: date | None
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


class AICitation(BaseModel):
    marker: str
    source_id: UUID
    chunk_id: UUID
    title: str
    source_url: str | None
    chamber: str | None
    docket_no: str | None
    decision_no: str | None
    decision_date: date | None
    excerpt: str
    rank: float


class AIAnswerResponse(BaseModel):
    question: str
    answer: str
    provider: str
    model: str
    citations: list[AICitation]
