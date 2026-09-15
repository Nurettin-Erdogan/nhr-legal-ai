from __future__ import annotations

from collections.abc import Iterator
from time import sleep
from typing import Any, Callable

from ingestion.catalog import PROFILES, STARTER_LAWS, LawJob
from ingestion.mevzuat.archive import LegislationArchive
from ingestion.mevzuat.models import LegislationRecord
from ingestion.mevzuat.parser import iter_article_nodes, record_from_article
from ingestion.mevzuat.portal import BASE_URL, MevzuatPortalClient, MevzuatPortalError
from ingestion.mevzuat.store import upsert_legislation
from worker.config import get_worker_settings
from worker.models import AdapterHealth, RecordOutcome, SyncRequest


class MevzuatSourceAdapter:
    source_name = "mevzuat"
    authority = "Adalet Bakanlığı / Bedesten"
    active = True
    official_source_url = BASE_URL

    def __init__(self, *, client: MevzuatPortalClient | None = None) -> None:
        self.client = client
        self.last_cursor: dict[str, Any] = {}

    def _settings(self):
        return get_worker_settings()

    def health_check(self) -> AdapterHealth:
        client = self.client or MevzuatPortalClient(timeout_seconds=20, max_retries=1)
        try:
            page = client.search_page(page_number=1, page_size=1, law_no="4857")
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
            "verified_against_gazette": False,
        }

    def _jobs(self, request: SyncRequest) -> tuple[LawJob, ...]:
        if request.law_no.strip():
            return (LawJob(request.law_no.strip(), request.law_no.strip()),)
        return PROFILES.get("starter", PROFILES["smoke"]).laws or STARTER_LAWS

    def sync(
        self,
        request: SyncRequest,
        *,
        cursor: dict[str, Any],
        connection: Any,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> Iterator[tuple[RecordOutcome, dict[str, Any]]]:
        settings = self._settings()
        jobs = self._jobs(request)
        start_index = int(cursor.get("law_index") or 0) if request.resume else 0
        start_index = min(start_index, max(0, len(jobs) - 1))
        max_articles = request.max_records or settings.mevzuat_max_articles
        client = self.client or MevzuatPortalClient(
            timeout_seconds=30,
            max_retries=settings.max_retries,
        )
        archive = LegislationArchive(settings.snapshot_dir + "/mevzuat")
        processed = 0
        law_index = start_index
        last_successful_article = str(cursor.get("last_article_no") or "")
        skip_until_article = last_successful_article if request.resume else ""
        stopped_on_unfinished = False

        for law_index in range(start_index, len(jobs)):
            if processed >= max_articles or should_stop() or stopped_on_unfinished:
                break
            job = jobs[law_index]
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
                # Kanun bulunamadı: sonraki kanuna geç; madde checkpoint'i ilerletme.
                skip_until_article = ""
                continue
            document = page.documents[0]
            tree = client.fetch_article_tree(str(document.get("mevzuatId")))
            articles = list(iter_article_nodes(tree))
            skipping = bool(skip_until_article)
            for article in articles:
                if processed >= max_articles or should_stop():
                    break
                article_no = str(article.get("maddeNo") or "").strip()
                if skipping:
                    if article_no == skip_until_article:
                        skipping = False
                    continue
                processed += 1
                extra = {
                    "law_no": job.law_no,
                    "article_no": article_no,
                    "law_index": law_index,
                    "requests_made": 1,
                }
                try:
                    if settings.mevzuat_delay_seconds:
                        sleep(settings.mevzuat_delay_seconds)
                    html = client.fetch_article_html(str(article.get("maddeId")))
                    extra["requests_made"] = 2
                    record = record_from_article(document=document, article=article, article_html=html)
                    missing = self.validate(record)
                    if missing:
                        yield "quarantined", {
                            **extra,
                            "external_id": record.external_id,
                            "reason": "missing_fields:" + ",".join(missing),
                            "raw": {"article": dict(article), "missing": missing},
                        }
                        # Checkpoint ilerletme; resume aynı maddeyi yeniden dener.
                        stopped_on_unfinished = True
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
                    stopped_on_unfinished = True
                    break
            skip_until_article = ""

        complete = (
            not stopped_on_unfinished
            and not should_stop()
            and law_index >= len(jobs) - 1
            and processed < max_articles
        )
        self.last_cursor = {
            "law_index": 0 if complete else law_index,
            "last_article_no": last_successful_article,
            "profile": "starter",
            "complete": complete,
        }
