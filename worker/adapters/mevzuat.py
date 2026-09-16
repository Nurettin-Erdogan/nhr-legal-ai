from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from time import sleep
from typing import Any, Callable

from ingestion.catalog import LawJob
from ingestion.mevzuat.archive import LegislationArchive
from ingestion.mevzuat.models import LegislationRecord
from ingestion.mevzuat.parser import iter_article_nodes, parse_portal_date, record_from_article
from ingestion.mevzuat.portal import (
    BASE_URL,
    MevzuatPortalClient,
    MevzuatPortalError,
    is_missing_article_tree_error,
)
from ingestion.mevzuat.store import upsert_legislation
from ingestion.mevzuat_bilgi_sistemi.portal import MbsClient, MbsError
from ingestion.resmi_gazete.portal import ResmiGazeteClient, ResmiGazeteError
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest

DISCOVERY_PAGE_SIZE = 10


class MevzuatSourceAdapter:
    source_name = "mevzuat"
    authority = "Adalet Bakanlığı / Bedesten"
    active = True
    official_source_url = BASE_URL

    def __init__(
        self,
        *,
        client: MevzuatPortalClient | None = None,
        gazette_client: ResmiGazeteClient | None = None,
        mbs_client: MbsClient | None = None,
        verify_gazette: bool = True,
        verify_mbs: bool = True,
    ) -> None:
        self.client = client
        self.gazette_client = gazette_client
        self.mbs_client = mbs_client
        self.verify_gazette = verify_gazette
        self.verify_mbs = verify_mbs
        self.last_cursor: dict[str, Any] = {}
        self._law_state: dict[str, Any] = {
            "processed": 0,
            "last_article": "",
            "finished": False,
            "stopped": False,
            "skipped_missing_tree": False,
        }

    def _settings(self):
        return get_worker_settings()

    def health_check(self) -> AdapterHealth:
        client = self.client or MevzuatPortalClient(timeout_seconds=20, max_retries=1)
        try:
            page = client.search_page(page_number=1, page_size=1)
            if not isinstance(page.total, int):
                return AdapterHealth(
                    self.source_name,
                    "degraded",
                    "searchDocuments total alanı beklenen sözleşmede değil",
                )
            return AdapterHealth(
                self.source_name,
                "healthy",
                "bedesten.adalet.gov.tr/mevzuat JSON sözleşmesi doğrulandı",
            )
        except MevzuatPortalError as exc:
            return AdapterHealth(self.source_name, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            return AdapterHealth(self.source_name, "failed", str(exc))

    def validate(self, record: LegislationRecord) -> list[str]:
        missing: list[str] = []
        if not record.law_name:
            missing.append("law_name")
        if not record.article_no:
            missing.append("article_no")
        if not record.raw_text.strip():
            missing.append("raw_text")
        if not record.external_id:
            missing.append("external_id")
        return missing

    def dedup_identity(self, record: LegislationRecord) -> str:
        return record.external_id

    def version_identity(self, record: LegislationRecord) -> str:
        return f"{record.version_date or 'undated'}:{record.content_hash}"

    def provenance(self, record: LegislationRecord) -> dict[str, Any]:
        return {
            "source_type": "legislation",
            "authority": self.authority,
            "canonical_source_name": "Mevzuat Bilgi Sistemi",
            "official_source_url": record.source_url,
            "external_id": record.external_id,
            "transport_source": BASE_URL,
            "canonical_legal_source": "Resmî Gazete / resmi mevzuat sistemi",
            "ingestion_method": "bedesten_public_json_http",
            "fetched_at": record.scraped_at.isoformat() if record.scraped_at else None,
            "published_at": (
                record.official_gazette_date.isoformat()
                if record.official_gazette_date
                else None
            ),
            "effective_from": record.effective_from.isoformat() if record.effective_from else None,
            "effective_to": record.effective_to.isoformat() if record.effective_to else None,
            "content_hash": record.content_hash,
            "source_version": self.version_identity(record),
            "official_gazette_no": record.official_gazette_no,
            "official_gazette_date": (
                record.official_gazette_date.isoformat()
                if record.official_gazette_date
                else None
            ),
            "verified_against_gazette": bool(
                record.metadata.get("verified_against_gazette", False)
            ),
            "official_gazette_verification": record.metadata.get(
                "official_gazette_verification"
            ),
            "verified_against_mbs": bool(record.metadata.get("verified_against_mbs", False)),
            "mbs_verification": record.metadata.get("mbs_verification"),
        }

    def _discovery_types(self) -> tuple[str, ...]:
        types = self._settings().mevzuat_discovery_types
        return types or ("KANUN",)

    def _law_job_from_document(self, document: dict[str, Any] | Any) -> LawJob | None:
        law_no = str(document.get("mevzuatNo") or "").strip()
        if not law_no:
            return None
        name = str(document.get("mevzuatAdi") or law_no).strip() or law_no
        tur = document.get("mevzuatTur")
        type_name = "KANUN"
        if isinstance(tur, dict):
            type_name = str(tur.get("name") or "KANUN").strip() or "KANUN"
        elif tur:
            type_name = str(tur).strip() or "KANUN"
        return LawJob(law_no, name, types=(type_name,))

    def _ingest_one_law(
        self,
        *,
        job: LawJob,
        document: Any,
        client: MevzuatPortalClient,
        archive: LegislationArchive,
        request: SyncRequest,
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
        max_articles: int,
        processed: int,
        skip_until_article: str,
        law_index: int,
        skip_missing_tree: bool,
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        state = {
            "processed": processed,
            "last_article": skip_until_article,
            "finished": False,
            "stopped": False,
            "skipped_missing_tree": False,
        }
        self._law_state = state
        gazette_date = parse_portal_date(document.get("resmiGazeteTarihi"))
        gazette_no = str(document.get("resmiGazeteSayisi") or "").strip() or None
        law_name = str(document.get("mevzuatAdi") or "").strip()
        mevzuat_id = str(document.get("mevzuatId") or "").strip()
        try:
            tree = client.fetch_article_tree(mevzuat_id)
        except MevzuatPortalError as exc:
            if not is_missing_article_tree_error(str(exc)):
                yield "failed", {
                    "external_id": None,
                    "reason": str(exc),
                    "law_no": job.law_no,
                    "requests_made": 1,
                }
                state["stopped"] = True
                return
            yield "quarantined", {
                "external_id": f"mevzuat:{job.law_no}:tree",
                "reason_code": "missing_article_tree",
                "reason": str(exc),
                "law_no": job.law_no,
                "raw": {
                    "law_no": job.law_no,
                    "mevzuat_id": mevzuat_id,
                    "detail": str(exc),
                },
                "requests_made": 1,
            }
            if skip_missing_tree:
                state["finished"] = True
                state["skipped_missing_tree"] = True
            else:
                state["stopped"] = True
            return
        articles = list(iter_article_nodes(tree))
        if not articles:
            yield "quarantined", {
                "external_id": f"mevzuat:{job.law_no}:tree",
                "reason_code": "missing_article_tree",
                "reason": f"Madde ağacı boş: {job.law_no}",
                "law_no": job.law_no,
                "raw": {"law_no": job.law_no, "mevzuat_id": mevzuat_id},
                "requests_made": 1,
            }
            if skip_missing_tree:
                state["finished"] = True
                state["skipped_missing_tree"] = True
            else:
                state["stopped"] = True
            return
        gazette_verification: dict[str, Any] = {
            "verified": False,
            "detail": "Resmî Gazete doğrulaması için tarih veya sayı bilgisi eksik",
        }
        pending_verification_requests = 0
        if self.verify_gazette and (gazette_date or gazette_no):
            pending_verification_requests = 3
            verifier = self.gazette_client or ResmiGazeteClient(
                max_retries=settings.max_retries,
                retry_backoff_seconds=max(1.0, settings.mevzuat_delay_seconds),
            )
            try:
                gazette_verification = verifier.verify_legislation(
                    publication_date=gazette_date,
                    issue_no=gazette_no,
                    law_no=job.law_no,
                    law_name=law_name,
                ).to_json()
            except ResmiGazeteError as exc:
                gazette_verification = {
                    "verified": False,
                    "detail": str(exc),
                    "requested_date": gazette_date.isoformat() if gazette_date else None,
                    "requested_issue_no": gazette_no,
                    "law_no": job.law_no,
                }
        mbs_verification: dict[str, Any] = {
            "verified": False,
            "detail": "MBS doğrulaması çalıştırılmadı",
            "law_no": job.law_no,
        }
        if self.verify_mbs:
            pending_verification_requests += 2
            mbs = self.mbs_client or MbsClient(
                max_retries=settings.max_retries,
                retry_backoff_seconds=max(1.0, settings.mevzuat_delay_seconds),
            )
            try:
                mbs_verification = mbs.verify_legislation(
                    law_no=job.law_no,
                    law_name=law_name,
                    publication_date=gazette_date,
                    issue_no=gazette_no,
                ).to_json()
            except MbsError as exc:
                mbs_verification = {
                    "verified": False,
                    "detail": str(exc),
                    "law_no": job.law_no,
                }
        skipping = bool(skip_until_article)
        law_finished = True
        last_successful_article = skip_until_article
        for article in articles:
            if state["processed"] >= max_articles or should_stop():
                law_finished = False
                break
            article_no = str(article.get("maddeNo") or "").strip()
            if skipping:
                if article_no == skip_until_article:
                    skipping = False
                continue
            state["processed"] += 1
            extra = {
                "law_no": job.law_no,
                "article_no": article_no,
                "law_index": law_index,
                "requests_made": 1 + pending_verification_requests,
            }
            try:
                if settings.mevzuat_delay_seconds:
                    sleep(settings.mevzuat_delay_seconds)
                html = client.fetch_article_html(str(article.get("maddeId")))
                extra["requests_made"] = 2 + pending_verification_requests
                record = record_from_article(document=document, article=article, article_html=html)
                record = replace(
                    record,
                    official_gazette_no=(
                        record.official_gazette_no
                        or str(gazette_verification.get("observed_issue_no") or "").strip()
                        or None
                    ),
                    official_gazette_date=(
                        record.official_gazette_date
                        or parse_portal_date(gazette_verification.get("observed_date"))
                    ),
                    metadata={
                        **record.metadata,
                        "verified_against_gazette": bool(
                            gazette_verification.get("verified", False)
                        ),
                        "official_gazette_url": gazette_verification.get("archive_url"),
                        "official_gazette_verification": gazette_verification,
                        "verified_against_mbs": bool(
                            mbs_verification.get("verified", False)
                        ),
                        "mbs_url": mbs_verification.get("detail_url"),
                        "mbs_pdf_url": mbs_verification.get("pdf_url"),
                        "mbs_verification": mbs_verification,
                    },
                )
                missing = self.validate(record)
                if missing:
                    yield "quarantined", {
                        **extra,
                        "external_id": record.external_id,
                        "reason_code": "missing_fields",
                        "reason": "missing_fields:" + ",".join(missing),
                        "raw": {"article": dict(article), "missing": missing},
                    }
                    state["stopped"] = True
                    law_finished = False
                    break
                archive.save(record)
                if dry_run:
                    yield "created", {
                        **extra,
                        "external_id": record.external_id,
                        "dry_run": True,
                    }
                    last_successful_article = article_no
                    continue
                result = upsert_legislation(connection, record)
                yield result.status, {  # type: ignore[misc]
                    **extra,
                    "external_id": result.external_id,
                    "legal_source_id": result.legal_source_id,
                }
                last_successful_article = article_no
            except (MevzuatPortalError, ValueError) as exc:
                yield "failed", {**extra, "reason": str(exc)}
                state["stopped"] = True
                law_finished = False
                break
        if skipping:
            yield "failed", {
                "external_id": None,
                "reason": f"Resume maddesi bulunamadı: {job.law_no} m.{skip_until_article}",
                "law_no": job.law_no,
                "requests_made": 0,
            }
            state["stopped"] = True
            law_finished = False
            last_successful_article = ""
        state["finished"] = law_finished
        state["last_article"] = "" if law_finished else last_successful_article

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        if request.law_no.strip():
            yield from self._sync_targeted(
                request,
                cursor=cursor,
                connection=connection,
                dry_run=dry_run,
                should_stop=should_stop,
            )
            return
        yield from self._sync_discovery(
            request,
            cursor=cursor,
            connection=connection,
            dry_run=dry_run,
            should_stop=should_stop,
        )

    def _sync_targeted(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        job = LawJob(request.law_no.strip(), request.law_no.strip())
        max_articles = request.max_records or settings.mevzuat_max_articles
        client = self.client or MevzuatPortalClient(
            timeout_seconds=30,
            max_retries=settings.max_retries,
        )
        archive = LegislationArchive(settings.snapshot_dir + "/mevzuat")
        skip_until_article = (
            str(cursor.get("last_article_no") or "")
            if request.resume and str(cursor.get("law_no") or "") == job.law_no
            else ""
        )
        page = client.search_page(
            page_number=1,
            page_size=1,
            law_no=job.law_no,
            types=job.types,
        )
        if not page.documents:
            yield "failed", {
                "external_id": None,
                "reason": f"Kanun bulunamadı: {job.law_no}",
                "law_no": job.law_no,
                "requests_made": 1,
            }
            self.last_cursor = {
                "law_index": 0,
                "law_no": job.law_no,
                "last_article_no": skip_until_article,
                "profile": "targeted",
                "complete": False,
            }
            return
        yield from self._ingest_one_law(
            job=job,
            document=page.documents[0],
            client=client,
            archive=archive,
            request=request,
            connection=connection,
            dry_run=dry_run,
            should_stop=should_stop,
            max_articles=max_articles,
            processed=0,
            skip_until_article=skip_until_article,
            law_index=0,
            skip_missing_tree=False,
        )
        state = self._law_state
        self.last_cursor = {
            "law_index": 0,
            "law_no": job.law_no,
            "last_article_no": state["last_article"],
            "profile": "targeted",
            "complete": bool(state["finished"] and not state["stopped"]),
        }

    def _sync_discovery(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        types = self._discovery_types()
        max_articles = request.max_records or settings.mevzuat_max_articles
        client = self.client or MevzuatPortalClient(
            timeout_seconds=30,
            max_retries=settings.max_retries,
        )
        archive = LegislationArchive(settings.snapshot_dir + "/mevzuat")
        resume = bool(request.resume)
        restart = resume and cursor.get("complete") and not cursor.get("last_article_no")
        type_index = 0 if restart or not resume else int(cursor.get("type_index") or 0)
        catalog_page = 1 if restart or not resume else int(cursor.get("catalog_page") or 1)
        catalog_offset = 0 if restart or not resume else int(cursor.get("catalog_offset") or 0)
        skip_until_article = (
            str(cursor.get("last_article_no") or "")
            if resume and not restart and cursor.get("law_no")
            else ""
        )
        pinned_law_no = (
            str(cursor.get("law_no") or "")
            if skip_until_article
            else ""
        )
        processed = 0
        stopped = False
        skipped_laws = 0
        current_law_no = pinned_law_no
        last_article = skip_until_article

        while processed < max_articles and not should_stop() and not stopped:
            if type_index >= len(types):
                break
            current_type = types[type_index]
            if pinned_law_no:
                page = client.search_page(
                    page_number=1,
                    page_size=1,
                    law_no=pinned_law_no,
                    types=(),
                )
                documents = page.documents
                job_offset = 0
            else:
                page = client.search_page(
                    page_number=catalog_page,
                    page_size=DISCOVERY_PAGE_SIZE,
                    types=(current_type,),
                )
                documents = page.documents
                job_offset = catalog_offset
            if not documents:
                if pinned_law_no:
                    yield "failed", {
                        "external_id": None,
                        "reason": f"Kanun bulunamadı: {pinned_law_no}",
                        "law_no": pinned_law_no,
                        "requests_made": 1,
                    }
                    stopped = True
                    break
                type_index += 1
                catalog_page, catalog_offset = 1, 0
                continue
            if job_offset >= len(documents):
                if len(documents) >= DISCOVERY_PAGE_SIZE and (
                    not page.total or catalog_page * DISCOVERY_PAGE_SIZE < page.total
                ):
                    catalog_page += 1
                    catalog_offset = 0
                else:
                    type_index += 1
                    catalog_page, catalog_offset = 1, 0
                continue
            document = documents[job_offset]
            job = self._law_job_from_document(document)
            if job is None:
                catalog_offset += 1
                pinned_law_no = ""
                skip_until_article = ""
                continue
            current_law_no = job.law_no
            yield from self._ingest_one_law(
                job=job,
                document=document,
                client=client,
                archive=archive,
                request=request,
                connection=connection,
                dry_run=dry_run,
                should_stop=should_stop,
                max_articles=max_articles,
                processed=processed,
                skip_until_article=skip_until_article,
                law_index=type_index * 1_000_000 + catalog_page * DISCOVERY_PAGE_SIZE + catalog_offset,
                skip_missing_tree=True,
            )
            state = self._law_state
            processed = state["processed"]
            last_article = state["last_article"]
            skip_until_article = ""
            pinned_law_no = ""
            if state["stopped"]:
                stopped = True
                if not state["finished"]:
                    pinned_law_no = current_law_no
                    skip_until_article = last_article
                break
            if state["finished"]:
                catalog_offset += 1
                last_article = ""
                current_law_no = ""
                if state.get("skipped_missing_tree"):
                    skipped_laws += 1
                    if skipped_laws >= 40:
                        break
            else:
                pinned_law_no = current_law_no
                skip_until_article = last_article
                break

        complete = not stopped and type_index >= len(types)
        self.last_cursor = {
            "mode": "discovery",
            "profile": "discovery",
            "type_index": min(type_index, max(0, len(types) - 1)),
            "catalog_page": catalog_page,
            "catalog_offset": catalog_offset,
            "law_no": pinned_law_no or current_law_no,
            "last_article_no": last_article,
            "complete": complete,
            "reconciled": complete,
            "window_complete": complete,
        }
