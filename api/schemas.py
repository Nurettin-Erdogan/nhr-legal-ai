from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from api.ai.answer_kind import AnswerKind


class HealthResponse(BaseModel):
    status: str
    database: str


class CourtDecisionBreakdown(BaseModel):
    yargitay: int = 0
    danistay: int = 0
    anayasa_mahkemesi: int = 0
    istinaf_emsal: int = 0


class AdministrativeBreakdown(BaseModel):
    kamu_denetciligi_kurumu: int = 0
    sayistay: int = 0
    uyusmazlik_mahkemesi: int = 0


class ThirdPartyBreakdown(BaseModel):
    """Resmî portalla doğrulanmamış (üçüncü taraf arşiv) kararlar, kaynak bazında."""

    yargitay: int = 0
    danistay: int = 0
    istinaf_emsal: int = 0
    aym_norm_denetimi: int = 0


class LegislationVerificationBreakdown(BaseModel):
    bedesten: int = 0
    both_verified: int = 0
    gazette_only: int = 0
    mbs_only: int = 0
    neither: int = 0


class ChunkEmbeddingBreakdown(BaseModel):
    ready: int = 0
    pending: int = 0


class CorpusStats(BaseModel):
    source_count: int
    chunk_count: int
    decision_count: int
    legislation_count: int
    other_count: int = 0
    latest_decision_date: date | None
    court_decisions: CourtDecisionBreakdown = Field(default_factory=CourtDecisionBreakdown)
    administrative: AdministrativeBreakdown = Field(default_factory=AdministrativeBreakdown)
    third_party: ThirdPartyBreakdown = Field(default_factory=ThirdPartyBreakdown)
    legislation_verification: LegislationVerificationBreakdown = Field(
        default_factory=LegislationVerificationBreakdown
    )
    embeddings: ChunkEmbeddingBreakdown = Field(default_factory=ChunkEmbeddingBreakdown)
    seed_count: int = 0


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
    # "official": resmî kaynakla doğrulanmış; "third_party": üçüncü taraf toplu veri, doğrulanmadı (aranır ve atıf yapılır
    # ama resmî diye sunulmaz); "unknown": durum okunamadı (resmî sayılmaz).
    verification: str = "unknown"


class LegalSearchResponse(BaseModel):
    query: str
    as_of: date | None = None
    total: int
    # true: doğrulanmamış toplu katmanın yalnız bir bölümü puanlandı veya tam sürüm zaman aşımına
    # uğrayıp sınırlı sürüme geçildi; sonuçlar eksik olabilir.
    partial: bool = False
    limit: int
    offset: int
    results: list[LegalSearchHit]


class LegalChunk(BaseModel):
    id: UUID
    chunk_index: int
    content: str


class LegalSourceDetail(BaseModel):
    id: UUID
    verification: str = "unknown"
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
    ollama_num_ctx: int | None = None
    ollama_max_output_tokens: int | None = None


class AIAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    project_id: UUID | None = None
    # Büro davası: dava belgeleri (UYAP dahil) kullanıcının özel belgeleri olarak aranır.
    case_id: UUID | None = None
    # Arayüzün büro projesi (office_projects); çekirdek projects tablosuyla karıştırılmaz.
    office_project_id: UUID | None = None
    # office_case_documents kimlikleri; bu seçim varsa bütün dava değil yalnız bu belgeler aranır.
    selected_document_ids: list[UUID] = Field(default_factory=list, max_length=40)
    as_of: date | None = None

    @model_validator(mode="after")
    def _single_document_scope(self) -> "AIAnswerRequest":
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("Soru boş olamaz")
        if sum(value is not None for value in (self.project_id, self.case_id, self.office_project_id)) > 1:
            raise ValueError("project_id, case_id ve office_project_id birlikte verilemez")
        if self.selected_document_ids and self.project_id is not None:
            raise ValueError("project_id ve selected_document_ids birlikte verilemez")
        self.selected_document_ids = list(dict.fromkeys(self.selected_document_ids))
        return self


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
    verification: str = "official"


class AIAnswerResponse(BaseModel):
    question: str
    as_of: date | None = None
    answer: str
    provider: str
    model: str
    citations: list[AICitation]
    # Modele verilen, doğrulanmış ama cevapta alıntılanmayan kaynaklar (en çok 8, kaynak başına bir pasaj).
    # Cevabın dayanağı değildir; kullanıcının ilgili kararları kendisinin okuyabilmesi içindir.
    consulted_sources: list[AICitation] = Field(default_factory=list)
    grounded: bool
    answer_kind: AnswerKind = "legal"
    unverified_markers: list[str] = Field(default_factory=list)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    from_cache: bool = False
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    done_reason: str | None = None
    # Request-local candidate counts, never the total matching corpus size.
    search_summary: dict[str, Any] | None = None
    # Takip sorusu önceki sorulara göre nasıl yorumlandı (yalnız arama içindir; kullanıcıya şeffaflık için gösterilir).
    interpreted_question: str | None = None
    # Uzun kanun maddesi cevabı için denetlenmiş kısa özet (yapay zekâ; dayanak aşağıdaki madde metnidir).
    summary: list[str] = Field(default_factory=list)
    # Dava kapsamlı sorularda: davadaki kaç belgenin cevaba katılabildiği, hangilerinin okunamadığı.
    document_scope: dict[str, Any] | None = None
