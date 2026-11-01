from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth.routes import current_user_id
from api.db import authenticated_database_connection, admin_database_connection
from worker import ACTIVE_SOURCES
from worker.lanes import CURRENT_LANE_SOURCES, canonical_source, checkpoint_name
from worker.monitoring import coverage_payload
from worker.repository import SyncRepository

router = APIRouter(prefix="/api/admin/ingestion", tags=["admin-ingestion"])


def require_admin(user_id: UUID = Depends(current_user_id)) -> UUID:
    with authenticated_database_connection(str(user_id)) as connection:
        row = connection.execute(
            "SELECT app_has_global_role('admin') AS is_admin"
        ).fetchone()
    if not row or not row["is_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu uç nokta yalnızca yönetici rolüne açıktır",
        )
    return user_id


@router.get("/status")
def ingestion_status(_admin: UUID = Depends(require_admin)) -> dict:
    with admin_database_connection() as connection:
        repo = SyncRepository(connection)
        checkpoints = repo.list_checkpoints()
        latest_runs = {}
        for checkpoint in checkpoints:
            latest_runs[checkpoint.source_name] = (
                repo.list_runs(source_name=checkpoint.source_name, limit=1) or [None]
            )[0]
    sources = []
    for checkpoint in checkpoints:
        run = latest_runs.get(checkpoint.source_name)
        job_name = checkpoint.source_name
        sources.append(
            {
                "source": canonical_source(job_name),
                "job": job_name,
                "lane": "current" if job_name.endswith(":current") else "backfill",
                "status": run["status"] if run else "idle",
                "health": checkpoint.health_state,
                "health_detail": checkpoint.health_detail,
                "last_successful_sync": checkpoint.last_successful_sync_at,
                "last_attempt": checkpoint.last_attempt_at,
                "next_run_at": checkpoint.next_run_at,
                "current_window": {
                    "date_from": checkpoint.last_date_from,
                    "date_to": checkpoint.last_date_to,
                    "page": checkpoint.last_page,
                },
                "records_created": run["created_count"] if run else 0,
                "records_updated": run["updated_count"] if run else 0,
                "records_duplicate": run["duplicate_count"] if run else 0,
                "records_failed": run["failed_count"] if run else 0,
                "last_error": checkpoint.last_error,
            }
        )
    return {"sources": sources}


@router.get("/runs")
def ingestion_runs(
    source: str | None = None,
    limit: int = 20,
    _admin: UUID = Depends(require_admin),
) -> dict:
    with admin_database_connection() as connection:
        rows = SyncRepository(connection).list_runs(source_name=source, limit=limit)
    return {"runs": rows}


@router.get("/sources")
def ingestion_sources(_admin: UUID = Depends(require_admin)) -> dict:
    return {
        "active": [
            {
                "source": "yargitay",
                "authority": "Yargıtay",
                "official_source_url": "https://karararama.yargitay.gov.tr",
                "transport": "karararama.yargitay.gov.tr JSON/HTTP",
            },
            {
                "source": "danistay",
                "authority": "Danıştay",
                "official_source_url": "https://karararama.danistay.gov.tr",
                "transport": "karararama.danistay.gov.tr JSON/HTTP",
            },
            {
                "source": "mevzuat",
                "authority": "Adalet Bakanlığı / Bedesten",
                "official_source_url": "https://bedesten.adalet.gov.tr/mevzuat/",
                "canonical_legal_source": "Resmî Gazete / resmi mevzuat sistemi",
                "transport": "bedesten.adalet.gov.tr/mevzuat",
            },
            {
                "source": "kdk",
                "authority": "Kamu Denetçiliği Kurumu",
                "official_source_url": "https://kararlar.ombudsman.gov.tr",
                "transport": "KDK public DataTables JSON + resmî PDF",
            },
            {
                "source": "aym",
                "authority": "Anayasa Mahkemesi",
                "official_source_url": "https://kararlarbilgibankasi.anayasa.gov.tr",
                "transport": "AYM public JSON + public UDF attachment",
            },
        ],
        "verification": [
            {
                "source": "resmi_gazete",
                "official_source_url": "https://www.resmigazete.gov.tr",
                "status": "active",
                "embedded_in": "mevzuat",
                "note": "Tarih, sayı ve mevzuat numarası resmî arşivle doğrulanır",
            },
            {
                "source": "mevzuat_bilgi_sistemi",
                "official_source_url": "https://www.mevzuat.gov.tr",
                "status": "active",
                "embedded_in": "mevzuat",
                "note": (
                    "Mevzuat numarası, başlığı, Resmî Gazete künyesi ve resmî "
                    "konsolide PDF/DOC bağlantıları doğrulanır"
                ),
            },
        ],
        "planned": [],
    }


@router.get("/coverage")
def ingestion_coverage(
    source: str | None = None,
    _admin: UUID = Depends(require_admin),
) -> dict:
    with admin_database_connection() as connection:
        return coverage_payload(connection, source_name=source)


@router.post("/run/{source}")
def request_ingestion_run(
    source: str,
    lane: str = "backfill",
    _admin: UUID = Depends(require_admin),
) -> dict:
    source = source.strip().lower()
    job_lane = "current" if source.endswith(":current") or lane == "current" else "backfill"
    canonical = canonical_source(source)
    if canonical not in ACTIVE_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yalnız ACTIVE kaynaklar kuyruğa alınabilir",
        )
    if job_lane == "current" and canonical not in CURRENT_LANE_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{canonical} current şeridine sahip değil",
        )
    from datetime import UTC, datetime

    job = checkpoint_name(canonical, job_lane)
    with admin_database_connection() as connection:
        repo = SyncRepository(connection)
        checkpoint = repo.get_checkpoint(job)
        checkpoint.next_run_at = datetime.now(UTC)
        repo.save_checkpoint(checkpoint)
        connection.commit()
    return {
        "source": canonical,
        "lane": job_lane,
        "job": job,
        "queued": True,
        "detail": "Daemon bir sonraki turda bu işi çalıştırır",
    }
