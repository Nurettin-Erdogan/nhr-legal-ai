"""Shared grounded-answer pipeline: retrieve, cache, generate, verify, persist."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from uuid import UUID

import psycopg
from fastapi import HTTPException
from psycopg.errors import InsufficientPrivilege

from api.audit import AI_ANSWER, AuditContext, record_event
from api.ai.case_questions import asks_for_legal_assessment, is_case_file_question
from api.ai.cache import (
    answer_cache,
    answer_cache_key,
    history_fingerprint,
    source_fingerprint,
)
from api.ai.conversation_history import (
    ConversationNotFound,
    load_conversation_context,
    retrieval_question,
    standalone_question,
)
from api.ai.embeddings import EmbeddingProviderError, create_embedding_provider
from api.embed_pause import pause_embeddings, resume_embeddings, unload_ollama_model
from api.ai.history import record_exchange
from api.document_indexing import case_document_coverage, sweep_unindexed
from api.ai.live_verify import verify_third_party_contexts
from api.ai.consulted_relevance import relevant_chunk_ids
from api.ai.discovery import candidate_pool_size, select_answer_contexts, search_summary
from api.ai.fast_statute import try_fast_statute
from api.ai.relevance import case_law_requested, documents_answer, documents_named_in
from api.ai.trust import usable_as_evidence, verified_contexts
from api.ai.turkish_text import restore_turkish
from api.ai.on_demand_verify import (
    explicit_statute_reference,
    verify_pending_statute,
    verify_relevant_pending_statute,
)
from api.ai.providers import AIProvider, AIProviderError, create_provider
from api.ai.rag import HistoryTurn, RAGContext, generate_grounded_answer
from api.ai.retrieval import retrieve_contexts, retrieve_document_contexts
from api.ai.verification import (
    VerifiedAnswer,
    has_insufficient_source_signal,
    is_insufficient_source_reply,
    prune_rejected_lines,
    verify_answer,
)
from api.config import get_settings
from api.db import authenticated_database_connection, database_connection
from api.ai import verification_queue
from api.schemas import AIAnswerRequest, AIAnswerResponse, AICitation

logger = logging.getLogger(__name__)

StageCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None]
_generation_lock = asyncio.Lock()
_PROGRESS_HEARTBEAT_SECONDS = 8.0
# Canlı portal doğrulaması LLM üretimiyle paralel çalışır. Önbellek isabetinde gizleyecek bir
# LLM süresi olmadığından yalnız kısa beklenir; LLM sonrasında ise doğrulamanın kendi bütçesi
# (`live_verify`) zaten sınırlı olduğundan bu değer yalnız emniyet payıdır.
_CACHE_HIT_VERIFY_WAIT_SECONDS = 2.0
_VERIFY_GRACE_SECONDS = 5.0
_PRE_GENERATION_VERIFY_WAIT_SECONDS = 15.0


@dataclass(slots=True)
class PipelineTimings:
    retrieval_ms: float = 0.0
    embedding_ms: float = 0.0
    prompt_build_ms: float = 0.0
    llm_ms: float = 0.0
    verification_ms: float = 0.0
    persist_ms: float = 0.0
    total_ms: float = 0.0
    from_cache: bool = False
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    done_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def as_citation(position: int, context: RAGContext) -> AICitation:
    return AICitation(
        marker=f"K{position}",
        source_id=context.source_id,
        chunk_id=context.chunk_id,
        source_type=context.source_type,
        title=context.title,
        reference=context.reference_line,
        source_url=context.source_url,
        court_name=context.court_name,
        chamber=context.chamber,
        docket_no=context.docket_no,
        decision_no=context.decision_no,
        decision_date=context.decision_date,
        law_name=context.law_name,
        law_no=context.law_no,
        article_no=context.article_no,
        page_number=context.page_number,
        version_date=context.version_date,
        effective_from=context.effective_from,
        effective_to=context.effective_to,
        source_version=context.source_version,
        revision=context.revision,
        excerpt=context.content[:500],
        rank=context.rank,
        verification=context.verification,
    )


CONSULTED_SOURCE_LIMIT = 8


def consulted_sources(
    answer: VerifiedAnswer, contexts: Sequence[RAGContext], question: str = ""
) -> list[AICitation]:
    """Cevaba girmeyen ama incelenen doğrulanmış kaynaklar: kaynak başına bir pasaj, I1, I2, ...

    Yalnız `usable_as_evidence` olanlar listelenir (resmî kaynak ya da kullanıcının kendi belgesi);
    doğrulanmamış üçüncü taraf kayıtlar buraya hiçbir koşulda girmez.
    """
    if not answer.grounded or not answer.contexts:
        # Cevap kaynaklardan çıkarılamadıysa aranan kaynaklar büyük olasılıkla soruyla ilgisizdir;
        # onları "incelendi" diye göstermek yanıltıcı olur.
        return []
    cited_chunks = {context.chunk_id for context in answer.contexts}
    seen_sources = {context.source_id for context in answer.contexts}
    # Sözcük eşleşmesi alakasız kararları da getirir; havuzda az kararda geçen soru kelimelerine göre
    # süzülür (bkz. consulted_relevance). Süzgeç yalnız gösterimi etkiler, cevabı değil.
    keep = relevant_chunk_ids(question, contexts) if question else None
    listed: list[AICitation] = []
    for context in contexts:
        if context.chunk_id in cited_chunks or context.source_id in seen_sources:
            continue
        if keep is not None and context.chunk_id not in keep:
            continue
        if not usable_as_evidence(context):
            continue
        seen_sources.add(context.source_id)
        position = len(listed) + 1
        listed.append(as_citation(position, context).model_copy(update={"marker": f"I{position}"}))
        if len(listed) >= CONSULTED_SOURCE_LIMIT:
            break
    return listed


def _queue_cited_third_party(answer: VerifiedAnswer) -> None:
    """Atıf yapılan doğrulanmamış kaynakları öncelikli doğrulama sırasına alır."""
    pending = [
        context.source_id
        for context in answer.contexts
        if context.verification == "third_party"
    ]
    verification_queue.enqueue_in_background(pending)


def _response_from_verified(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    provider: AIProvider,
    conversation_id: UUID | None,
    message_id: UUID | None,
    from_cache: bool,
    timings: PipelineTimings | None = None,
    consulted: Sequence[RAGContext] = (),
) -> AIAnswerResponse:
    if any(not usable_as_evidence(context) for context in answer.contexts):
        raise HTTPException(503, "Kaynak doğrulaması tamamlanamadı; doğrulanmamış atıflar gösterilmiyor.")
    if not from_cache:
        _queue_cited_third_party(answer)
    return AIAnswerResponse(
        question=request.question,
        as_of=request.as_of,
        answer=answer.text,
        provider=provider.name,
        model=provider.model,
        citations=[
            as_citation(position, context)
            for position, context in enumerate(answer.contexts, start=1)
        ],
        consulted_sources=consulted_sources(answer, consulted, request.question),
        grounded=answer.grounded,
        unverified_markers=list(answer.unverified_markers),
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=from_cache,
        prompt_eval_count=None if timings is None else timings.prompt_eval_count,
        eval_count=None if timings is None else timings.eval_count,
        done_reason=None if timings is None else timings.done_reason,
        search_summary=None if timings is None else timings.extra.get('search_summary'),
        interpreted_question=None if timings is None else timings.extra.get('interpreted_question'),
        summary=list(answer.summary),
        document_scope=(
            None if timings is None else (timings.extra.get('retrieval') or {}).get('document_scope')
        ),
    )


def _payload_from_response(response: AIAnswerResponse) -> dict[str, Any]:
    return response.model_dump(
        mode="json",
        exclude={
            "conversation_id",
            "message_id",
            "from_cache",
            "prompt_eval_count",
            "eval_count",
            "done_reason",
            "document_scope",  # her istekte yeniden hesaplanır; önbellekte bayatlar
            "interpreted_question",
        },
    )


async def _embed_question(question: str) -> list[float] | None:
    settings = get_settings()
    try:
        provider = create_embedding_provider(
            provider_name=settings.embedding_provider,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=min(8.0, settings.ollama_timeout_seconds),
        )
        from api.ai.relevance import semantic_search_text
        return await asyncio.to_thread(provider.embed_query, semantic_search_text(question))
    except EmbeddingProviderError:
        logger.warning("Soru embedding'i üretilemedi; lexical RAG kullanılacak")
        return None


def _consume_task_result(task: "asyncio.Future[Any]") -> None:
    """Beklenmeyen bir görevin istisnası "never retrieved" uyarısına dönmesin."""
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Canlı doğrulama görevi başarısız", exc_info=task.exception())


def _start_live_verification(
    contexts: list[RAGContext],
    *, target_sources: int = 6, diagnostics: dict | None = None,
) -> "asyncio.Future[list[RAGContext]] | None":
    """Doğrulanmamış kaynak varsa portal doğrulamasını arka planda başlatır."""
    if not any(context.verification == "third_party" for context in contexts):
        return None
    task = asyncio.ensure_future(asyncio.to_thread(
        verify_third_party_contexts, contexts, max_docs=12,
        target_sources=target_sources, diagnostics=diagnostics,
    ))
    task.add_done_callback(_consume_task_result)
    return task


async def _resolve_verification(
    task: "asyncio.Future[list[RAGContext]] | None",
    contexts: list[RAGContext],
    *,
    wait: float,
    timings: PipelineTimings,
) -> list[RAGContext]:
    """Paralel doğrulamanın sonucunu alır.

    Bitmediyse ya da hata verdiyse rozetler olduğu gibi kalır: kaynak "doğrulanmadı" görünmeye
    devam eder, yani yavaş bir portal cevabı yanlış biçimde "resmî" gösteremez. Görev iptal
    edilmez (kalıcı terfi kendi başına tamamlanır); yalnız bu cevap onu beklemez.
    """
    if task is None:
        return contexts
    started = monotonic()
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=wait)
        timings.extra["live_verify"] = "done"
        return result
    except asyncio.TimeoutError:
        logger.info("Canlı doğrulama %.1f sn içinde bitmedi; kaynaklar doğrulanmadı kalıyor", wait)
        timings.extra["live_verify"] = "timeout"
        return contexts
    except Exception:
        logger.warning("Canlı doğrulama sonucu alınamadı", exc_info=True)
        timings.extra["live_verify"] = "error"
        return contexts
    finally:
        timings.extra["live_verify_wait_ms"] = round((monotonic() - started) * 1000, 1)


def _source_preview(contexts: list[RAGContext]) -> list[dict[str, Any]]:
    """Cevap hazır olmadan gösterilecek kaynak özeti. İddia içermez: yalnız künye ve durum."""
    return [
        {
            "marker": f"K{position}",
            "source_id": str(context.source_id),
            "source_type": context.source_type,
            "reference": context.reference_line,
            "verification": context.verification,
        }
        for position, context in enumerate(contexts, start=1)
    ]


async def _load_history(
    request: AIAnswerRequest, user_id: UUID | None
) -> tuple[tuple[HistoryTurn, ...], tuple[str, ...]]:
    """Devam eden sohbetin önceki turlarını ve son sorularını RLS altında okur."""
    if request.conversation_id is None:
        return (), ()
    if user_id is None:
        raise HTTPException(
            status_code=401, detail="Sohbeti sürdürmek için oturum açmalısınız"
        )

    def load():
        with authenticated_database_connection(str(user_id)) as connection:
            return load_conversation_context(connection, request.conversation_id)

    try:
        context = await asyncio.to_thread(load)
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı") from exc
    except psycopg.Error as exc:
        logger.exception("Sohbet geçmişi okunamadı")
        raise HTTPException(
            status_code=503, detail="Sohbet geçmişi okunamadı"
        ) from exc
    if request.project_id != context.project_id:
        raise HTTPException(
            status_code=409, detail="Bu sohbet farklı bir projeye ait"
        )
    questions = getattr(context, "questions", ()) or tuple(turn.question for turn in context.turns)
    return context.turns, questions


def persist_answer(
    request: AIAnswerRequest,
    answer: VerifiedAnswer,
    *,
    user_id: UUID,
    model_name: str,
    audit: AuditContext | None = None,
    from_cache: bool = False,
) -> tuple[UUID | None, UUID | None]:
    try:
        with authenticated_database_connection(str(user_id)) as connection:
            conversation_id, message_id = record_exchange(
                connection,
                user_id=user_id,
                conversation_id=request.conversation_id,
                project_id=request.project_id,
                question=request.question,
                answer=answer,
                model_name=model_name,
                as_of=request.as_of,
            )
            # Soru ve cevap metni denetim günlüğüne yazılmaz; yalnız olayın özeti.
            record_event(
                connection,
                action=AI_ANSWER,
                actor_user_id=user_id,
                context=audit,
                entity_type="conversation",
                entity_id=conversation_id,
                project_id=request.project_id,
                metadata={
                    "message_id": str(message_id),
                    "model": model_name,
                    "grounded": answer.grounded,
                    "from_cache": from_cache,
                    "citation_count": len(answer.contexts),
                    "third_party_citations": sum(
                        1 for context in answer.contexts if context.verification == "third_party"
                    ),
                    "document_citations": sum(
                        1 for context in answer.contexts if context.source_type == "document"
                    ),
                },
                strict=False,
            )
            return conversation_id, message_id
    except InsufficientPrivilege as exc:
        raise HTTPException(
            status_code=403,
            detail="Bu konuşmaya veya projeye yazma yetkiniz yok",
        ) from exc
    except psycopg.Error:
        logger.exception("Sohbet geçmişi kaydedilemedi")
        return None, None


def _interleave(first: list[RAGContext], second: list[RAGContext]) -> list[RAGContext]:
    """İki listeyi, kendi sıralarını bozmadan birer birer birleştirir (ilk öğe `first` listesinden)."""
    merged: list[RAGContext] = []
    for index in range(max(len(first), len(second))):
        merged.extend(items[index] for items in (first, second) if index < len(items))
    return merged


_CASE_STATUTE_ARTICLES = 2
_CASE_STATUTE_CHUNKS = 3


def _case_statute_contexts(connection, question: str, named_documents: list[RAGContext]) -> list[RAGContext]:
    """Hukuki soruya, konusuna uyan resmî doğrulanmış kanun maddelerini ekler (genel sohbet ve dava sohbeti).

    "İhtarnamede verilen süre kanuna uygun mu?" sorusunun sözcükleri hangi kanunun söz konusu olduğunu söylemez; sözcük
    araması ilgisiz kararlar getiriyordu (ölçüldü: 2026-10-06). Konu önce sorudan, soruda yoksa sorunun adıyla gösterdiği
    belgenin metninden çıkarılır (bütün dosyadan değil: başka belgelerdeki sözcükler konuyu saptırır). Madde numaraları
    sabit tablodan gelir (`api.statute_hints`), metin korpustan okunur ve beklenen konuyu taşımıyorsa eklenmez; burada
    hiçbir metin üretilmez. Eklenen madde yalnız ADAYDIR: cümle alaka süzgecinden ve kaynak-destek denetiminden geçer.
    """
    from api import statute_hints
    from api.ai.retrieval import STATUTE_RETRIEVAL_SQL, _execute_retrieval

    hints = statute_hints.suggest(question)
    if not hints and named_documents:
        hints = statute_hints.suggest(question + " " + " ".join(c.content[:1500] for c in named_documents[:2]))
    found: list[RAGContext] = []
    for hint in hints[:_CASE_STATUTE_ARTICLES]:
        try:
            with connection.transaction():  # zaman aşımı yalnız bu ek sorguyu düşürür, asıl aramayı değil
                rows = _execute_retrieval(
                    connection, STATUTE_RETRIEVAL_SQL,
                    {"law_no": hint.law_no, "article_no": hint.article_no, "as_of": None, "top_k": _CASE_STATUTE_CHUNKS},
                    timeout="2s",
                )
        except psycopg.Error:
            logger.warning("Dava sorusu için madde ipucu okunamadı: %s m.%s", hint.law_no, hint.article_no)
            continue
        rows = [row for row in rows if row.source_type == "legislation" and row.verification == "official"]
        if rows and statute_hints.text_matches(hint, " ".join(row.content for row in rows)):
            found.extend(rows)
    return found


def _retrieve(
    request: AIAnswerRequest,
    *,
    user_id: UUID | None,
    query_embedding: list[float] | None,
    top_k: int,
    embedding_model: str,
    question: str | None = None,
    diagnostics: dict | None = None,
) -> list[RAGContext]:
    search_question = question or request.question
    if request.project_id is not None or request.case_id is not None:
        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Proje belgeleriyle çalışmak için oturum açmalısınız",
            )
        if request.case_id is not None:
            # Hangi yoldan geldiğinden bağımsız, henüz indekslenmemiş dava belgelerini bütçe içinde hazırlar.
            sweep_unindexed(user_id, case_id=request.case_id)
            if diagnostics is not None:
                diagnostics["document_scope"] = case_document_coverage(user_id, request.case_id)
        file_only = request.case_id is not None and is_case_file_question(search_question)
        with authenticated_database_connection(str(user_id)) as connection:
            document_contexts = retrieve_document_contexts(
                connection,
                question=search_question,
                project_id=None if request.project_id is None else str(request.project_id),
                case_id=None if request.case_id is None else str(request.case_id),
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
            )
            legal_assessment = asks_for_legal_assessment(search_question)
            named: list[RAGContext] = []
            if request.case_id is not None:
                named = documents_named_in(search_question, document_contexts)
                if named:
                    # Soru bir belgeyi adıyla gösteriyor ("ihtarnamede…"): yalnız o belgenin parçaları aranır. Hukuki
                    # değerlendirme de istenmiyorsa başka hiçbir kaynağa bakılmaz.
                    document_contexts = named
                    file_only = file_only or not legal_assessment
            if (
                request.case_id is not None
                and not file_only
                and not legal_assessment
                and documents_answer(search_question, document_contexts)
            ):
                # Dosya sözcüğü taşımayan olgu sorusu ("Depozito tutarı nedir?"): cevabı davanın belgelerinde yazıyorsa
                # yalnız o belgelerden cevaplanır. Karışık aramada model, kullanıcının sözleşmesi yerine başka bir davanın
                # kararındaki tutarı cevap diye seçebiliyordu (ölçüldü: 2026-10-06).
                file_only = True
            if diagnostics is not None:
                diagnostics["case_file_only"] = file_only
                if isinstance(diagnostics.get("document_scope"), dict):
                    diagnostics["document_scope"]["file_only"] = file_only
            if file_only:
                # "Davalının adresi nedir?" gibi kendi dosyasına dair soru: başka davaların kararlarından
                # alıntı yapılmaz; belgelerde yoksa "yeterli bilgi yok" denir.
                return document_contexts[:top_k]
            legal_contexts = retrieve_contexts(
                connection,
                question=search_question,
                top_k=top_k,
                query_embedding=query_embedding,
                embedding_model=embedding_model,
                as_of=request.as_of,
                diagnostics=diagnostics,
            )
            # Dava belgeleri ve hukuk kaynaklarının puanları aynı ölçekte değildir (ts_rank / RRF): iki liste kendi içinde
            # sıralanır ve sırayla birer birer alınır; ilk sırada kullanıcının kendi belgesi vardır. Belgeler önce, hukuk
            # kaynakları sonra dizildiğinde çok belgeli davada modele giden ilk kaynakların tamamı belge oluyor, hukuki
            # değerlendirme sorusu hiçbir hukuk kaynağına ulaşamıyordu (ölçüldü: 2026-10-06).
            if named and not case_law_requested(search_question):
                # Kullanıcının kendi belgesi hakkındaki hukuki soru ("ihtarnamede verilen süre kanuna uygun mu?"): başka
                # davaların kararları kullanılmaz. O kararlardaki olay cümleleri ("ihtarnamede 30 günlük süre verilmiş
                # olması nedeniyle … hukuki sonuç doğurmaz") kullanıcının belgesi hakkında söylenmiş gibi okunuyor; ölçülen
                # örnekte cümle ürün kirasına (TBK 362) ilişkindi, soru konut kirasıydı (2026-10-06). Kuralı kanun maddesi,
                # olguyu belge söyler. İçtihat isteyen soru ("Yargıtay", "emsal"…) bu süzgece girmez.
                legal_contexts = [context for context in legal_contexts if context.source_type == "legislation"]
            own = sorted(document_contexts, key=lambda context: context.rank, reverse=True)
            statutes = (
                _case_statute_contexts(connection, search_question, named) if request.case_id is not None else []
            )
            known = {context.chunk_id for context in statutes}
            others = [
                *statutes,
                *(c for c in sorted(legal_contexts, key=lambda context: context.rank, reverse=True) if c.chunk_id not in known),
            ]
            return _interleave(own, others)[:top_k]
    with database_connection() as connection:
        contexts = retrieve_contexts(
            connection,
            question=search_question,
            top_k=top_k,
            query_embedding=query_embedding,
            embedding_model=embedding_model,
            as_of=request.as_of,
            diagnostics=diagnostics,
        )
        if request.as_of is None:
            # Genel soruda da konuya uyan resmî madde adayların başına eklenir. Sözcük araması "işe iade davası açma
            # süresi" sorusuna yalnız 2015-2016 kararlarını getiriyordu; o kararlar arabuluculuk zorunluluğundan önceki
            # usulü anlatır, güncel kural İş Kanunu m. 20'dedir (ölçüldü: 2026-10-06). Tarihli sorularda (as_of) eklenmez:
            # madde yalnız güncel hâliyle okunur.
            statutes = _case_statute_contexts(connection, search_question, [])
            if statutes:
                known = {context.chunk_id for context in statutes}
                contexts = [*statutes, *(context for context in contexts if context.chunk_id not in known)]
                if diagnostics is not None:
                    diagnostics["topic_statutes"] = len({context.source_id for context in statutes})
        return contexts


async def _retrieve_with_warm_retry(request: AIAnswerRequest, **kwargs: Any) -> list[RAGContext]:
    """Soğuk önbellekte tüm arama kolları zaman aşımına uğrayabilir (API/veritabanı yeni açıldığında
    ya da uzun boşlukta ilk soru; ölçüldü: 2026-10-03). İlk deneme okuduğu sayfaları önbelleğe
    bıraktığından yeniden deneme çoğunlukla geçer; ikinci başarısızlık gerçek hata sayılır."""
    for attempt in (1, 2):
        try:
            return await asyncio.to_thread(_retrieve, request, **kwargs)
        except psycopg.errors.QueryCanceled:
            if attempt == 2:
                raise
            logger.warning("Arama zaman aşımına uğradı (soğuk önbellek olabilir); bir kez yeniden deneniyor")
    raise AssertionError("unreachable")


async def execute_answer(
    request: AIAnswerRequest,
    user_id: UUID | None,
    *,
    on_stage: StageCallback | None = None,
    audit: AuditContext | None = None,
    _force_full_search: bool = False,
) -> tuple[AIAnswerResponse, PipelineTimings]:
    settings = get_settings()
    timings = PipelineTimings()
    started = monotonic()

    async def emit(stage: str, **extra: Any) -> None:
        if on_stage is None:
            return
        result = on_stage({"stage": stage, **extra})
        if asyncio.iscoroutine(result):
            await result

    await emit("searching")
    pause_embeddings("assistant")
    try:
        if not settings.rag_query_embedding:
            await asyncio.to_thread(
                unload_ollama_model, settings.ollama_base_url, settings.embedding_model
            )
        return await _execute_answer_body(
            request,
            user_id,
            settings=settings,
            timings=timings,
            started=started,
            emit=emit,
            audit=audit,
            _force_full_search=_force_full_search,
        )
    finally:
        resume_embeddings()


async def _execute_answer_body(
    request: AIAnswerRequest,
    user_id: UUID | None,
    *,
    settings,
    timings: PipelineTimings,
    started: float,
    emit: StageCallback,
    audit: AuditContext | None = None,
    _force_full_search: bool = False,
) -> tuple[AIAnswerResponse, PipelineTimings]:
    history, prior_questions = await _load_history(request, user_id)

    try:
        provider = create_provider(
            provider_name=settings.ai_provider,
            model=settings.ai_model,
            ollama_base_url=settings.ollama_base_url,
            ollama_timeout_seconds=settings.ollama_timeout_seconds,
            ollama_max_output_tokens=settings.ollama_max_output_tokens,
            ollama_num_ctx=settings.ollama_num_ctx,
            ollama_keep_alive=settings.ollama_keep_alive,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Takip sorusu ("Peki bunun süresi?") önceki sorulara göre tek başına anlaşılır hâle getirilir; sonuç kodla
    # denetlenir (bkz. conversation_history.accept_rewrite) ve yalnız arama ile kanıt seçimini yönlendirir.
    interpreted: str | None = None
    if prior_questions:
        rewrite_started = monotonic()
        async with _generation_lock:
            interpreted = await asyncio.to_thread(
                standalone_question, provider, restore_turkish(request.question), prior_questions
            )
        timings.extra["question_rewrite_ms"] = round((monotonic() - rewrite_started) * 1000, 1)
        timings.extra["interpreted_question"] = interpreted
    # Türkçe karakter olmadan yazılan soru ("davaci kac yil") arama için geri getirilir; kullanıcının
    # yazdığı soru (`request.question`) olduğu gibi saklanır.
    search_question = restore_turkish(interpreted or retrieval_question(request.question, history))
    answer_question = interpreted or restore_turkish(request.question)

    verify_task: asyncio.Future[list[RAGContext]] | None = None
    warmup_task: asyncio.Task[None] | None = None
    warmup = getattr(provider, "warmup", None)
    if callable(warmup):
        warmup_task = asyncio.create_task(asyncio.to_thread(warmup))

    try:
        fast_diagnostics: dict = {}
        fast_contexts = [] if _force_full_search else await asyncio.to_thread(
            try_fast_statute, question=search_question, as_of=request.as_of,
            project_id=request.project_id or request.case_id, conversation_id=request.conversation_id,
            max_chunks=settings.rag_top_k, max_chars=settings.rag_context_chars,
            diagnostics=fast_diagnostics,
        )
        timings.extra.update(fast_diagnostics)
        embed_started = monotonic()
        query_embedding = (
            await _embed_question(search_question)
            if settings.rag_query_embedding and not fast_contexts
            else None
        )
        timings.embedding_ms = (
            (monotonic() - embed_started) * 1000 if query_embedding else 0.0
        )

        statute_reference = explicit_statute_reference(search_question)
        if statute_reference is not None and request.as_of is None and not fast_contexts:
            law_no, article_no = statute_reference
            await emit(
                "verifying_source",
                source_type="legislation",
                law_no=law_no,
                article_no=article_no,
            )
            verification_started = monotonic()
            verification_status = await asyncio.to_thread(
                verify_pending_statute,
                search_question,
                as_of=request.as_of,
            )
            timings.extra["on_demand_legislation"] = verification_status
            timings.extra["on_demand_legislation_ms"] = round(
                (monotonic() - verification_started) * 1000,
                1,
            )

        if request.as_of is None and not fast_contexts:
            relevant_verification_started = monotonic()
            relevant_verification_status = await asyncio.to_thread(
                verify_relevant_pending_statute,
                search_question,
                as_of=request.as_of,
            )
            timings.extra[
                "on_demand_relevant_legislation"
            ] = relevant_verification_status
            timings.extra["on_demand_relevant_legislation_ms"] = round(
                (monotonic() - relevant_verification_started) * 1000,
                1,
            )

        retrieval_started = monotonic()
        retrieval_diagnostics: dict = dict(fast_diagnostics) if fast_contexts else {}
        verification_diagnostics: dict = {}
        try:
            contexts = fast_contexts or await _retrieve_with_warm_retry(
                request,
                user_id=user_id,
                query_embedding=query_embedding,
                top_k=candidate_pool_size(settings.rag_top_k),
                embedding_model=settings.embedding_model,
                question=search_question,
                diagnostics=retrieval_diagnostics,
            )
        except HTTPException:
            raise
        except psycopg.Error as exc:
            logger.exception("Hukuk kaynakları aranamadı")
            raise HTTPException(
                status_code=503, detail="Hukuk kaynakları aranamadı"
            ) from exc
        timings.retrieval_ms = (monotonic() - retrieval_started) * 1000 + fast_diagnostics.get('fast_statute_ms', 0)
        # Portal verification overlaps model warmup, never answer generation.
        candidates = list(contexts)
        timings.extra['retrieval'] = retrieval_diagnostics
        await emit('candidates_found', candidate_chunks=len(candidates),
                   candidate_documents=len({c.source_id for c in candidates}),
                   partial=bool(retrieval_diagnostics.get('partial')), exhaustive=False)
        verify_task = _start_live_verification(
            contexts, target_sources=settings.rag_top_k, diagnostics=verification_diagnostics,
        )
        if warmup_task is not None:
            await warmup_task
            warmup_task = None
    finally:
        if warmup_task is not None:
            warmup_task.cancel()
            try:
                await warmup_task
            except (asyncio.CancelledError, Exception):
                pass

    # Verify BEFORE cache, source previews or generation. A timeout must not
    # release pending text to the model or user, even if it is correctly quoted.
    if verify_task is not None:
        await emit("verifying_source", source_type="court_decision")
        contexts = await _resolve_verification(
            verify_task, contexts, wait=_PRE_GENERATION_VERIFY_WAIT_SECONDS, timings=timings
        )
        verify_task = None
    contexts = verified_contexts(contexts)
    verified_pool = contexts
    contexts = select_answer_contexts(verified_pool, settings.rag_top_k, question=search_question)
    verification_stats = dict(verification_diagnostics)
    if timings.extra.get('live_verify') in ('timeout', 'error'):
        verification_stats['stop_reason'] = timings.extra['live_verify']
    summary = search_summary(candidates, verified_pool, contexts,
                             retrieval_diagnostics, verification_stats)
    timings.extra['search_summary'] = summary
    timings.extra['verification'] = verification_stats
    timings.extra['unverified_excluded'] = summary['unverified_excluded']
    logger.info('RAG discovery %s', summary)
    await emit('search_summary', **summary)
    if not contexts:
        pending = int((retrieval_diagnostics.get('document_scope') or {}).get('pending') or 0)
        if request.case_id is not None and pending:
            # Asıl neden "kaynak yok" değil, davadaki belgelerin henüz hazır olmaması (ör. OCR sürüyor).
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Bu davadaki {pending} belge henüz işleniyor (taranmış belgeler OCR ile okunur, "
                    "birkaç dakika sürebilir). İşlem bitince soruyu tekrar sorun."
                ),
            )
        raise HTTPException(
            status_code=422,
            detail="Bu soru için yeterli resmî doğrulanmış kaynak bulunamadı. Portal doğrulaması tamamlanmamış veya eşleşmeyen kayıtlar cevaba alınmadı.",
        )

    await emit("sources_found", count=len(contexts), sources=_source_preview(contexts))
    fingerprint = source_fingerprint(contexts)
    cache_key = answer_cache_key(
        # Aynı takip sorusu farklı konularda farklı yorumlanır: yorumlanmış soru anahtarın parçasıdır.
        question=request.question if interpreted is None else f"{request.question} | {interpreted}",
        project_id=request.project_id or request.case_id,
        as_of=request.as_of,
        model=provider.model,
        fingerprint=fingerprint,
        history_key=history_fingerprint(history),
    )
    cached = answer_cache.get(cache_key)
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    if cached is not None:
        timings.from_cache = True
        cached_contexts = await _resolve_verification(
            verify_task, contexts, wait=_CACHE_HIT_VERIFY_WAIT_SECONDS, timings=timings
        )
        cited_ids = [item["chunk_id"] for item in cached["citations"]]
        by_id = {str(context.chunk_id): context for context in cached_contexts}
        ordered = tuple(by_id[chunk_id] for chunk_id in cited_ids if chunk_id in by_id)
        cached_answer = verify_answer(cached["answer"], list(ordered), question=search_question,
                                      available_contexts=contexts)
        if len(ordered) != len(cited_ids):
            cached = None
        if cached is not None and cached_answer.grounded:
            from dataclasses import replace as _replace
            cached_answer = _replace(cached_answer, summary=tuple(str(item) for item in (cached.get("summary") or ())))
            persist_started = monotonic()
            if user_id is not None:
                conversation_id, message_id = await asyncio.to_thread(
                    persist_answer,
                    request,
                    cached_answer,
                    user_id=user_id,
                    model_name=provider.model,
                    audit=audit,
                    from_cache=True,
                )
            timings.persist_ms = (monotonic() - persist_started) * 1000
            timings.total_ms = (monotonic() - started) * 1000
            response = _response_from_verified(
                request,
                cached_answer,
                provider=provider,
                conversation_id=conversation_id,
                message_id=message_id,
                from_cache=True,
                timings=timings,
                consulted=verified_pool,
            )
            await emit("done", result=response.model_dump(mode="json"))
            return response, timings

    # Old/invalid cache entries must go through generation and the current gate.
    timings.from_cache = False
    await emit("generating")
    try:
        async with _generation_lock:
            llm_started = monotonic()
            raw_answer = await asyncio.to_thread(
                generate_grounded_answer,
                provider,
                # Kanıt cümlelerini seçen alaka filtresi aksanlara duyarlıdır: ASCII yazılmış soru burada
                # da geri getirilir (aksi halde tüm cümleler elenir, model hiç çağrılmaz).
                question=answer_question,
                contexts=contexts,
                max_context_chars=settings.rag_context_chars,
                history=history,
            )
            timings.llm_ms = (monotonic() - llm_started) * 1000
    except AIProviderError as exc:
        usage = getattr(provider, "last_usage", None)
        if usage is not None:
            timings.prompt_eval_count = usage.prompt_eval_count
            timings.eval_count = usage.eval_count
            timings.done_reason = usage.done_reason
            timings.extra["num_predict"] = usage.num_predict
            timings.extra["num_ctx"] = usage.num_ctx
            logger.info(
                "Ollama generation failed prompt_eval_count=%s eval_count=%s done_reason=%s num_predict=%s num_ctx=%s",
                usage.prompt_eval_count,
                usage.eval_count,
                usage.done_reason,
                usage.num_predict,
                usage.num_ctx,
            )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    usage = getattr(provider, "last_usage", None)
    if usage is not None:
        timings.prompt_eval_count = usage.prompt_eval_count
        timings.eval_count = usage.eval_count
        timings.done_reason = usage.done_reason
        timings.extra["num_predict"] = usage.num_predict
        timings.extra["num_ctx"] = usage.num_ctx
        logger.info(
            "Ollama generation prompt_eval_count=%s eval_count=%s done_reason=%s num_predict=%s num_ctx=%s",
            usage.prompt_eval_count,
            usage.eval_count,
            usage.done_reason,
            usage.num_predict,
            usage.num_ctx,
        )

    await emit("verifying")
    final_contexts = await _resolve_verification(
        verify_task, contexts, wait=_VERIFY_GRACE_SECONDS, timings=timings
    )
    verify_started = monotonic()
    answer = verify_answer(raw_answer, final_contexts, question=search_question)
    if not answer.grounded:
        # Taslak yalnız kaynaktan aynen alınmış cümlelerden oluşur. Bir cümle denetimden geçmediğinde (konu dışı ya da
        # desteklenmeyen) cevabın tamamı reddedilmez: o satırlar atılır, kalan metin baştan ve aynı denetimle doğrulanır.
        pruned = prune_rejected_lines(raw_answer, answer)
        if pruned is not None:
            retried = verify_answer(pruned, final_contexts, question=search_question)
            if retried.grounded:
                timings.extra['pruned_lines'] = len(raw_answer.splitlines()) - len(pruned.splitlines())
                answer = retried
    timings.verification_ms = (monotonic() - verify_started) * 1000
    if fast_contexts and not answer.grounded:
        # A plausible provision is not proof that it answers the question.
        # Run the full pipeline once; no unsupported fast draft is published.
        timings.extra['fast_statute_fallback'] = 'unsupported_draft'
        return await _execute_answer_body(
            request, user_id, settings=settings, timings=timings, started=started,
            emit=emit, audit=audit, _force_full_search=True,
        )
    if not answer.grounded:
        logger.warning(
            "Atıfsız taslak: %s | desteklenmeyen=%s | çözülmeyen işaret=%s | atıf=%d",
            raw_answer[:400], list(answer.unsupported_claims)[:4], list(answer.unverified_markers), len(answer.contexts),
        )
        if is_insufficient_source_reply(
            answer.text or raw_answer
        ) or has_insufficient_source_signal(raw_answer):
            answer = VerifiedAnswer(
                text=(
                    "Mevcut doğrulanmış kaynaklarda bu soruya güvenilir ve kaynaklı "
                    "bir cevap vermek için yeterli bilgi bulunmuyor."
                ),
                contexts=(),
                unverified_markers=answer.unverified_markers,
            )
        else:
            raise HTTPException(
                status_code=422,
                detail="Yanıt kaynak metniyle doğrulanamadı; desteklenmeyen hukuki iddialar gösterilmiyor",
            )

    if answer.grounded and getattr(settings, "rag_explanations", False):
        from api.ai.explanation import explain_verified_answer
        explanation_started = monotonic()
        async with _generation_lock:
            answer = await asyncio.to_thread(
                explain_verified_answer, provider, question=search_question, answer=answer,
            )
        timings.extra["explanation_ms"] = round((monotonic() - explanation_started) * 1000, 1)

    from api.ai import statute_summary
    if statute_summary.eligible(answer):
        # Uzun madde metninin üstüne denetlenmiş kısa özet: cevap metni ve atıflar değişmez (bkz. statute_summary).
        from dataclasses import replace as _replace
        summary_started = monotonic()

        async def _summary_generate(system: str, prompt: str) -> str:
            async with _generation_lock:
                return await asyncio.to_thread(provider.generate, system_instruction=system, prompt=prompt)

        # Özet ek bir model çağrısıdır ve uzun maddede dakikaya yaklaşabilir (ölçüldü: 85 sn, 2026-10-06). Doğrulanmış
        # cevap o sırada hazırdır: önizleme olarak gönderilir, kullanıcı özeti beklerken cevabı okur. Önizleme kaydedilmez;
        # kalıcı cevap (özetiyle) her zamanki gibi "done" ile gelir.
        from api.ai.explanation import with_coverage_notice as _with_notice
        preview = _response_from_verified(
            request, _with_notice(answer, search_question), provider=provider, conversation_id=None,
            message_id=None, from_cache=False, timings=timings, consulted=verified_pool,
        )
        await emit("summarizing", preview=preview.model_dump(mode="json"))
        answer = _replace(answer, summary=await statute_summary.build(answer_question, answer, _summary_generate))
        timings.extra["statute_summary_ms"] = round((monotonic() - summary_started) * 1000, 1)
        timings.extra["statute_summary_bullets"] = len(answer.summary)

    from api.ai.explanation import with_coverage_notice
    answer = with_coverage_notice(answer, search_question)
    persist_started = monotonic()
    if user_id is not None:
        conversation_id, message_id = await asyncio.to_thread(
            persist_answer,
            request,
            answer,
            user_id=user_id,
            model_name=provider.model,
            audit=audit,
        )
    timings.persist_ms = (monotonic() - persist_started) * 1000
    response = _response_from_verified(
        request,
        answer,
        provider=provider,
        conversation_id=conversation_id,
        message_id=message_id,
        from_cache=False,
        timings=timings,
        consulted=verified_pool,
    )
    if answer.grounded:
        answer_cache.put(cache_key, _payload_from_response(response))
    timings.total_ms = (monotonic() - started) * 1000
    await emit("done", result=response.model_dump(mode="json"))
    return response, timings


async def iter_answer_events(
    request: AIAnswerRequest,
    user_id: UUID | None,
    audit: AuditContext | None = None,
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_stage(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def run() -> None:
        try:
            await execute_answer(request, user_id, on_stage=on_stage, audit=audit)
        except HTTPException as exc:
            await queue.put(
                {"stage": "error", "status": exc.status_code, "detail": exc.detail}
            )
        except Exception:
            logger.exception("AI yanıt üretimi başarısız")
            await queue.put(
                {
                    "stage": "error",
                    "status": 500,
                    "detail": "AI yanıtı üretilemedi",
                }
            )
        finally:
            await queue.put({"stage": "_end"})

    task = asyncio.create_task(run())
    try:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=_PROGRESS_HEARTBEAT_SECONDS,
                )
            except TimeoutError:
                yield {"stage": "ping"}
                continue
            if event.get("stage") == "_end":
                break
            yield event
    finally:
        await task
