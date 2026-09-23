from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .models import HistoricalJob, ImageAsset, JobImage
from .normalizer import NormalizedJob


def _now() -> datetime:
    return datetime.now(UTC)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def upsert_job(session: Session, normalized: NormalizedJob, *, run_id: UUID) -> UUID:
    now = _now()
    job_values = {
        "id": uuid4(),
        "source_system": normalized.source_system,
        "source_job_id": normalized.source_job_id,
        "external_order_id": normalized.external_order_id,
        "status": normalized.status,
        "team_outsource": normalized.team_outsource,
        "job_type": normalized.job_type,
        "order_id": normalized.order_id,
        "product_name": normalized.product_name,
        "sku": normalized.sku,
        "product_category": normalized.product_category,
        "note_outsource": normalized.note_outsource,
        "raw_preview_url": normalized.raw_preview_url,
        "preview_url": normalized.preview_url,
        "preview_source_path": normalized.preview_source_path,
        "preview_missing": normalized.preview_missing,
        "source_payload_hash": normalized.source_payload_hash,
        "ingest_source": "historical_backfill",
        "last_seen_at": now,
        "last_seen_run_id": run_id,
    }
    job_insert = insert(HistoricalJob).values(job_values)
    job_insert = job_insert.on_conflict_do_update(
        constraint="uq_support_compare_historical_job_source_id",
        set_={
            "external_order_id": job_insert.excluded.external_order_id,
            "status": job_insert.excluded.status,
            "team_outsource": job_insert.excluded.team_outsource,
            "job_type": job_insert.excluded.job_type,
            "order_id": job_insert.excluded.order_id,
            "product_name": job_insert.excluded.product_name,
            "sku": job_insert.excluded.sku,
            "product_category": job_insert.excluded.product_category,
            "note_outsource": job_insert.excluded.note_outsource,
            "raw_preview_url": job_insert.excluded.raw_preview_url,
            "preview_url": job_insert.excluded.preview_url,
            "preview_source_path": job_insert.excluded.preview_source_path,
            "preview_missing": job_insert.excluded.preview_missing,
            "source_payload_hash": job_insert.excluded.source_payload_hash,
            "last_seen_at": job_insert.excluded.last_seen_at,
            "last_seen_run_id": job_insert.excluded.last_seen_run_id,
        },
    )
    session.execute(job_insert)
    job_id = session.scalar(
        select(HistoricalJob.id).where(
            HistoricalJob.source_system == normalized.source_system,
            HistoricalJob.source_job_id == normalized.source_job_id,
        )
    )
    if not job_id:
        raise RuntimeError(f"Could not resolve upserted historical job {normalized.source_job_id}")

    # Flush a previous job-image insert before deleting the same primary role.
    # This matters if one API page contains the same source job more than once.
    session.flush()
    session.execute(
        delete(JobImage).where(JobImage.job_id == job_id, JobImage.role == "preview")
    )
    if normalized.preview_url:
        asset_id = upsert_asset(
            session,
            source_system=normalized.source_system,
            raw_url=normalized.raw_preview_url,
            url=normalized.preview_url,
        )
        session.add(
            JobImage(
                job_id=job_id,
                asset_id=asset_id,
                role="preview",
                position=0,
                is_primary=True,
            )
        )
    return job_id


def upsert_asset(session: Session, *, source_system: str, raw_url: str | None, url: str) -> UUID:
    now = _now()
    url_hash = _url_hash(url)
    asset_insert = insert(ImageAsset).values(
        id=uuid4(),
        source_system=source_system,
        url_sha256=url_hash,
        raw_url=raw_url,
        url=url,
        last_seen_at=now,
    )
    asset_insert = asset_insert.on_conflict_do_update(
        constraint="uq_support_compare_image_asset_url",
        set_={
            "raw_url": asset_insert.excluded.raw_url,
            "url": asset_insert.excluded.url,
            "last_seen_at": asset_insert.excluded.last_seen_at,
        },
    )
    session.execute(asset_insert)
    asset_id = session.scalar(
        select(ImageAsset.id).where(
            ImageAsset.source_system == source_system,
            ImageAsset.url_sha256 == url_hash,
        )
    )
    if not asset_id:
        raise RuntimeError(f"Could not resolve upserted image asset {url_hash}")
    return asset_id
