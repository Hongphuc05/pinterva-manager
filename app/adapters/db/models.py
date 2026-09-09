from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.db.base import Base


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    account_username: Mapped[str] = mapped_column(String(128), nullable=False)
    account_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Printerval's design-job/find endpoint rejects an unscoped query (see
    # docs/superpowers/specs/2026-09-07-printerval-api-crawl-design.md) — each mother
    # account has its own team scope. Previously this lived only in the process-wide
    # Settings/.env, so switching the active platform silently broke crawling for every
    # OTHER platform (last login's team_outsource clobbered the global value). Per
    # platform is the root-cause fix.
    team_outsource: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_cookie: Mapped[str | None] = mapped_column(Text, nullable=True)
    printerval_designer_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    printerval_status_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    printerval_options_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'designer')", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    capacity: Mapped[int | None] = mapped_column(nullable=True)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id"), nullable=True)
    # The exact visible label this designer is registered under in Printerval's own
    # per-team Designer <select> (e.g. "Nguyễn Thị Thuý Hường - 2D Prin") — live-
    # confirmed the site supports real per-designer sub-users (ng-options bound to
    # item.attributes.designer_email, admin-editable), not just the single shared
    # claim account NTTH_DESIGNER_OPTION was hardcoded to. NULL means this designer
    # has no Printerval registration yet (or none needed) — assignment sync is
    # skipped, not guessed, for that case. Set by admin, must match an option that
    # genuinely exists on the site or the write dead-letters (EXTERNAL_CHANGED).
    printerval_designer_option: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="ntth")
    count: Mapped[int] = mapped_column(nullable=False, default=0)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("platform_id", "external_order_id", name="uq_orders_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    external_observation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_variants: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Loại design job (2D/3D/ART/...) — chưa xác nhận được vị trí hiển thị per-order
    # trong DOM (chỉ là tiêu chí filter, không phải field hiển thị). Cột giữ chỗ, không
    # ai ghi vào cột này ở V1 — xem 2026-09-07-order-detail-mirror-design.md §3.
    job_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    multiple_design: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    double_sided: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    priority_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Naive datetime — site's display timezone chưa xác nhận (claude.md §17 #8), không
    # đoán UTC/local. Không dùng DateTime(timezone=True) như các cột audit khác.
    created_at_ext: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    order_created_at_ext: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    deadline_at_ext: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    note_outsource: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    previous_note_outsource: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    fix_approved_by_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    order_note: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    custom_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    template_jobs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    design_tool_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sku_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    external_order_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_download_all_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    printerval_designer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    printerval_designer_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Printerval's own live site status (waiting/doing/review/fix/confirm/done — the 6
    # literal values live-confirmed 2026-09-08, see PrintervalApiClient.ORDER_STATUSES)
    # — a READ-ONLY mirror kept in sync by a scheduled job + manual refresh, distinct
    # from `state` (our own internal workflow state machine, claude.md §5). Nothing in
    # this app ever writes this value back to Printerval; see claude.md §2 invariant #5
    # and §3 C5 — only a QC Approve decision's own job is allowed to write site state.
    printerval_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    printerval_status_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __mapper_args__ = {"version_id_col": version}


class OrderAsset(Base):
    __tablename__ = "order_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    source_image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    storage_location: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    designer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    sub_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    replacement_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PrintervalAssignmentRequest(Base):
    """Auditable per-order intent and outcome for an external Designer/Status update."""

    __tablename__ = "printerval_assignment_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id"), nullable=False)
    internal_designer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    designer_option: Mapped[str] = mapped_column(String(255), nullable=False)
    target_status: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    observed_designer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    observed_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ResultVersion(Base):
    __tablename__ = "result_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    drive_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    version_marker: Mapped[int] = mapped_column(nullable=False, default=1)
    validated: Mapped[bool] = mapped_column(nullable=False, default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint("kind IN ('assignment', 'qc')", name="ck_approval_requests_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    target_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("result_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    approval_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("approval_requests.id"), unique=True, nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExternalObservation(Base):
    __tablename__ = "external_observations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Operation(Base):
    __tablename__ = "operations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    command_name: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("operations.id"), nullable=True
    )
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error_class: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_action: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformSyncState(Base):
    """One row per platform, tracking the background order-status sync job (read-only
    mirror of Printerval's own status, see Order.printerval_status) — lets the web
    dashboard show a live "syncing / idle" indicator without polling Celery directly."""

    __tablename__ = "platform_sync_state"

    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id"), primary_key=True)
    is_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
