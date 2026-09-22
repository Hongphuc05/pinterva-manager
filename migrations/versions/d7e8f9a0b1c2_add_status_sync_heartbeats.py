"""add heartbeat and worker identity to status sync state

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-09-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d7e8f9a0b1c2"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_sync_state", sa.Column("worker_task_id", sa.String(length=255), nullable=True))
    op.add_column("platform_sync_state", sa.Column("run_token", sa.UUID(), nullable=True))
    op.add_column(
        "platform_sync_state",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("platform_sync_state", sa.Column("progress", postgresql.JSONB(), nullable=True))

    op.add_column("sync_jobs", sa.Column("worker_task_id", sa.String(length=255), nullable=True))
    op.add_column(
        "sync_jobs",
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("sync_jobs", sa.Column("progress_phase", sa.String(length=64), nullable=True))
    op.add_column("sync_jobs", sa.Column("current_order_code", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("sync_jobs", "current_order_code")
    op.drop_column("sync_jobs", "progress_phase")
    op.drop_column("sync_jobs", "last_heartbeat_at")
    op.drop_column("sync_jobs", "worker_task_id")
    op.drop_column("platform_sync_state", "progress")
    op.drop_column("platform_sync_state", "last_heartbeat_at")
    op.drop_column("platform_sync_state", "run_token")
    op.drop_column("platform_sync_state", "worker_task_id")
