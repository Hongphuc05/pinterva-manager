from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

SCHEMA_NAME = "support_compare_image"


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        CheckConstraint(
            "run_status IN ('running', 'completed', 'failed', 'stopped')",
            name="ck_support_compare_crawl_run_status",
        ),
        Index("ix_support_compare_crawl_runs_status", "run_status"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="printerval")
    team_outsource: Mapped[str] = mapped_column(String(128), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    target_statuses: Mapped[list] = mapped_column(JSONB, nullable=False)
    page_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    run_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default=text("'running'")
    )
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    stored_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    preview_missing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    malformed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CrawlCheckpoint(Base):
    __tablename__ = "crawl_checkpoints"
    __table_args__ = (
        UniqueConstraint("run_id", "status", name="uq_support_compare_checkpoint_run_status"),
        Index("ix_support_compare_checkpoints_resume", "run_id", "completed", "next_page_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.crawl_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    next_page_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rows_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rows_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    preview_missing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    malformed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    api_total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CrawlError(Base):
    __tablename__ = "crawl_errors"
    __table_args__ = (
        Index("ix_support_compare_crawl_errors_run", "run_id", "status", "page_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.crawl_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    page_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HistoricalJob(Base):
    __tablename__ = "historical_jobs"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_job_id", name="uq_support_compare_historical_job_source_id"
        ),
        Index("ix_support_compare_historical_jobs_status", "status"),
        Index("ix_support_compare_historical_jobs_external_code", "external_order_id"),
        Index("ix_support_compare_historical_jobs_product_name", "product_name"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="printerval")
    source_job_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    team_outsource: Mapped[str] = mapped_column(String(128), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False, default="all")
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(256), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    note_outsource: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_source_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    preview_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    source_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingest_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="historical_backfill", server_default=text("'historical_backfill'")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.crawl_runs.id", ondelete="SET NULL"),
        nullable=True,
    )


class ImageAsset(Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        UniqueConstraint("source_system", "url_sha256", name="uq_support_compare_image_asset_url"),
        Index("ix_support_compare_image_assets_fetch_status", "fetch_status"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False, default="printerval")
    url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default=text("'pending'")
    )
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobImage(Base):
    __tablename__ = "job_images"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "role", "position", name="uq_support_compare_job_image_role_position"
        ),
        Index("ix_support_compare_job_images_asset", "asset_id"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.historical_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.image_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="preview")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class ComparisonRun(Base):
    __tablename__ = "comparison_runs"
    __table_args__ = (
        Index("ix_support_compare_comparison_runs_status", "run_status", "source_kind"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    run_status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    baseline_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    promote_new_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComparisonItem(Base):
    __tablename__ = "comparison_items"
    __table_args__ = (
        Index(
            "ix_support_compare_comparison_items_order",
            "platform_id",
            "order_id",
            "processing_status",
        ),
        Index("ix_support_compare_comparison_items_run_status", "run_id", "processing_status"),
        UniqueConstraint(
            "run_id",
            "order_id",
            "image_url_sha256",
            "model_version",
            name="uq_support_compare_comparison_item_source",
        ),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    platform_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_printerval_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_order_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    image_url_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    phash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    color_l: Mapped[float | None] = mapped_column(nullable=True)
    color_a: Mapped[float | None] = mapped_column(nullable=True)
    color_b: Mapped[float | None] = mapped_column(nullable=True)
    classification: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_duplicate: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pool_promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pool_promotion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now)


class ComparisonCandidate(Base):
    __tablename__ = "comparison_candidates"
    __table_args__ = (
        Index(
            "ix_support_compare_candidates_review_queue",
            "classification",
            "decision_status",
            "telegram_notified_at",
        ),
        UniqueConstraint(
            "comparison_item_id",
            "historical_asset_id",
            "classifier_version",
            name="uq_support_compare_candidate_asset_classifier",
        ),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_item_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    historical_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    historical_asset_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    matched_external_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    matched_product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    matched_image_url: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    visual_similarity: Mapped[float] = mapped_column(nullable=False)
    phash_distance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssim: Mapped[float | None] = mapped_column(nullable=True)
    color_delta_e: Mapped[float | None] = mapped_column(nullable=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    classifier_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now)
