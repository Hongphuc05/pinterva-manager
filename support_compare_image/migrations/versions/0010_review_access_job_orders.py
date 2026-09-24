"""review password, per-job order snapshot, machine grants without device codes"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_review_access_job_orders"
down_revision: str | None = "0009_worker_devices_search_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"
ACTIVE_INDEX = "uq_support_compare_jobs_active_platform"


def upgrade() -> None:
    # The hidden "Duyệt trùng" area is locked by a password of its own (one per platform).
    op.create_table(
        "review_access",
        sa.Column("platform_id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        # Bumped on every password change so tokens issued before it stop working.
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    # Every "Có" on Telegram is its own job with a frozen list of orders, so several jobs can wait.
    op.add_column("comparison_jobs", sa.Column("order_ids", postgresql.JSONB(), nullable=True), schema=SCHEMA)
    op.drop_index(ACTIVE_INDEX, table_name="comparison_jobs", schema=SCHEMA)
    # Machines are now granted from the web session (no code typed), so the code columns go unused.
    op.alter_column("worker_devices", "user_code", existing_type=sa.String(length=16), nullable=True, schema=SCHEMA)
    op.alter_column(
        "worker_devices", "device_code_hash", existing_type=sa.String(length=64), nullable=True, schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_column("comparison_jobs", "order_ids", schema=SCHEMA)
    op.drop_table("review_access", schema=SCHEMA)
