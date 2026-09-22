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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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
    # When enabled, every designer-trello may rebalance duplicate cards between
    # every Trello column. Admins may always do so.
    duplicate_board_cross_designer_drag_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    standard_order_rate: Mapped[int] = mapped_column(
        nullable=False, default=40000, server_default=text("40000")
    )
    duplicate_order_rate: Mapped[int] = mapped_column(
        nullable=False, default=40000, server_default=text("40000")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'designer', 'designer-trello', 'support')", name="ck_users_role"),
        CheckConstraint(
            "telegram_delivery_mode IN ('private', 'group')",
            name="ck_users_telegram_delivery_mode",
        ),
        Index(
            "uq_users_telegram_group_chat_id",
            "telegram_group_chat_id",
            unique=True,
            postgresql_where=text("telegram_group_chat_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # Telegram integration
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    telegram_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    telegram_link_code: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    telegram_link_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    # A designer can keep the existing private chat connection and optionally
    # bind one verified group chat.  `telegram_delivery_mode` controls which
    # destination the designer notification service uses.
    telegram_group_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_group_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_group_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    telegram_group_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    telegram_group_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    telegram_group_last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    telegram_delivery_mode: Mapped[str] = mapped_column(
        String(16), default="private", server_default=text("'private'"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def platform_designer_option(self) -> str | None:
        return self.printerval_designer_option


class UserBankQr(Base):
    """Private bank-account QR images owned by a designer or support user."""

    __tablename__ = "user_bank_qr_images"
    __table_args__ = (
        UniqueConstraint("user_id", "sort_order", name="uq_user_bank_qr_sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
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
    __table_args__ = (
        UniqueConstraint("platform_id", "external_order_id", name="uq_orders_platform_external_id"),
        CheckConstraint(
            "duplicate_check_status IN ('uncheck', 'duplicate', 'non_duplicate')",
            name="ck_orders_duplicate_check_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id"), nullable=True)
    # `duplicate` is the shared Trello workspace. It is separate from the internal
    # workflow state so moving a card between people never mutates production state.
    work_domain: Mapped[str] = mapped_column(
        String(32), nullable=False, default="standard", server_default=text("'standard'")
    )
    duplicate_check_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="uncheck", server_default=text("'uncheck'")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    # Short-lived exclusive lease for active manual processing.  This supplements
    # optimistic versioning; it is never acquired merely by viewing or editing notes.
    processing_lock_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    processing_lock_acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_lock_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_observation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product_variants: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Normalized list of every sellable SKU included in this design job.  One order
    # may contain multiple sizes/variants; each item keeps its own image,
    # category, variants and custom configuration.
    product_skus: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Loại design job (2D/3D/ART/...) — chưa xác nhận được vị trí hiển thị per-order
    # trong DOM (chỉ là tiêu chí filter, không phải field hiển thị). Cột giữ chỗ, không
    # ai ghi vào cột này ở V1 — xem 2026-09-07-order-detail-mirror-design.md §3.
    job_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
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
    # Internal deadline chosen by Tacahu Admin for the crawl batch that first
    # imported this order. It is deliberately independent from the source site's
    # deadline_at_ext and is never refreshed from Printerval.
    deadline_tacahu: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A Fix approved by Admin has a short, explicit designer deadline.  The
    # notification timestamp is persisted so the periodic overdue scanner is
    # idempotent rather than spamming Admin on every run.
    fix_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note_outsource: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    previous_note_outsource: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    fix_approved_by_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    fix_rejected_by_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # Number of distinct transitions to Fix observed from Printerval. This is
    # intentionally separate from internal admin/designer actions.
    fix_return_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    # Internal instruction from Admin to the assigned Designer.  This is kept
    # separate from `note_outsource`, which mirrors Printerval QC feedback.
    designer_note: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    # A Designer-reported missing template is an internal exception queue.  It
    # deliberately does not re-introduce template crawling.
    template_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    template_missing_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    template_missing_reported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    template_missing_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Timestamp of the Admin's explicit release after a Designer reported a
    # missing template. It powers a short-lived acknowledgement in the
    # Designer queue without changing the durable workflow state.
    template_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set to True when Admin resolves a missing-template report so the Designer
    # does not see the Printerval note_outsource during that resolution cycle.
    # Cleared back to False when the order is next synced from the platform or
    # when note_outsource is updated via normal admin flows.
    suppress_note_outsource_for_designer: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Explicit provenance for the only note a Designer may see: an Admin-written
    # instruction released with an approved Fix. Existing notes intentionally
    # default to hidden until an Admin releases a new Fix instruction.
    designer_note_released_for_fix: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    order_note: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
    custom_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    design_tool_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sku_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    external_order_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_files: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_download_all_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    product_image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    printerval_designer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    printerval_designer_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Printerval's own live site status (waiting/doing/review/fix/confirm/done — the 6
    # literal values live-confirmed 2026-09-08, see PrintervalApiClient.ORDER_STATUSES)
    # — a READ-ONLY mirror kept in sync by a scheduled job + manual refresh, distinct
    # from `state` (our own internal workflow state machine, claude.md §5). Nothing in
    # this app ever writes this value back to Printerval; see claude.md §2 invariant #5
    printerval_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    printerval_status_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_paid: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    custom_rate: Mapped[int | None] = mapped_column(nullable=True)
    duplicate_board_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __mapper_args__ = {"version_id_col": version}

    @property
    def platform_status(self) -> str | None:
        return self.printerval_status

    @property
    def platform_status_synced_at(self) -> datetime | None:
        return self.printerval_status_synced_at

    @property
    def platform_designer(self) -> str | None:
        return self.printerval_designer

    @property
    def platform_assignment_lifecycle(self) -> str | None:
        return self.printerval_assignment_lifecycle

    @property
    def platform_assignment_error(self) -> str | None:
        return self.printerval_assignment_error


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


class OrderWorkNote(Base):
    """An append-only, Tacahu-owned collaboration note for one order."""

    __tablename__ = "order_work_notes"
    __table_args__ = (
        UniqueConstraint("order_id", "author_id", "idempotency_key", name="uq_order_work_note_request"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrderWorkNoteAttachment(Base):
    """Private image attached to an immutable work-note entry."""

    __tablename__ = "order_work_note_attachments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("order_work_notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OrderWorkNoteRead(Base):
    """The most recent work-note entry an operator has opened for an order."""

    __tablename__ = "order_work_note_reads"
    __table_args__ = (
        UniqueConstraint("order_id", "user_id", name="uq_order_work_note_read_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    worker_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_token: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class SyncJob(Base):
    """Durable progress for a user-requested or scheduled synchronization job."""

    __tablename__ = "sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platforms.id"), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    order_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total: Mapped[int] = mapped_column(nullable=False, default=0)
    processed: Mapped[int] = mapped_column(nullable=False, default=0)
    updated: Mapped[int] = mapped_column(nullable=False, default=0)
    failed: Mapped[int] = mapped_column(nullable=False, default=0)
    worker_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_order_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FinanceNote(Base):
    """Admin notes on orders or designers for tracking, payroll notes, and reviews."""

    __tablename__ = "finance_notes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platforms.id"), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # 'order' or 'designer'
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    order_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    designer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    designer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Admin")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TelegramActionLog(Base):
    """Audit log & opaque token store for Telegram inline callbacks (Approve/Reject Fix, etc.)."""

    __tablename__ = "telegram_action_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    callback_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramFixConversation(Base):
    """Per-admin Telegram delivery state for cleaning a completed Fix flow."""

    __tablename__ = "telegram_fix_conversations"
    __table_args__ = (
        UniqueConstraint("order_id", "chat_id", "root_message_id", name="uq_telegram_fix_conversation_root"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    root_message_id: Mapped[int] = mapped_column(nullable=False)
    transient_message_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    cleaned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TelegramMessageTemplate(Base):
    """Admin-editable text template for a Telegram notification event."""

    __tablename__ = "telegram_message_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"), nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TelegramConfigurationAudit(Base):
    """Append-only audit for Admin changes to Telegram routing/templates."""

    __tablename__ = "telegram_configuration_audits"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
