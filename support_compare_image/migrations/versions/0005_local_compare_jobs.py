"""add the local-worker comparison job queue"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_local_compare_jobs"
down_revision: str | None = "0004_support_unchecked_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.create_table(
        "comparison_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False, server_default=sa.text("'support_unchecked'")),
        sa.Column("platform_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "source_kind IN ('support_unchecked')",
            name="ck_support_compare_job_source_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_support_compare_job_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_jobs_claim",
        "comparison_jobs",
        ["status", "created_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_jobs_notification",
        "comparison_jobs",
        ["status", "notification_sent_at", "finished_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("comparison_jobs", schema=SCHEMA)
