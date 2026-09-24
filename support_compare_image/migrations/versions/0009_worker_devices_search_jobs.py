"""worker devices (device login) and the image-search queue"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_worker_devices_search_jobs"
down_revision: str | None = "0008_historical_custom_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.create_table(
        "worker_devices",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("machine_name", sa.String(length=128), nullable=False),
        sa.Column("user_code", sa.String(length=16), nullable=False),
        sa.Column("device_code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        # Set when a signed-in Support/Admin approves the code.
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("platform_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        # Plain token kept only until the agent's first poll after approval collects it.
        sa.Column("token_delivery", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        # Heartbeat from the approving user's open web page; the device may only work
        # while it is fresh (closing the web / logging out stops the worker).
        sa.Column("presence_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("busy_with", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'revoked')", name="ck_support_worker_device_status"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_support_worker_devices_device_code", "worker_devices", ["device_code_hash"], unique=True, schema=SCHEMA
    )
    op.create_index(
        "uq_support_worker_devices_token", "worker_devices", ["token_hash"], unique=True, schema=SCHEMA
    )
    op.create_index("ix_support_worker_devices_user_code", "worker_devices", ["user_code"], schema=SCHEMA)

    op.create_table(
        "search_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("platform_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        # Dropped (NULL) once the search finishes.
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("top_k", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("device_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')", name="ck_support_search_job_status"
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_support_search_jobs_claim", "search_jobs", ["status", "created_at"], schema=SCHEMA)

    op.add_column(
        "comparison_jobs", sa.Column("device_id", sa.UUID(as_uuid=True), nullable=True), schema=SCHEMA
    )
    # Keyset paging of the pool (agents download it in chunks and then only the delta).
    op.create_index(
        "ix_support_image_embeddings_pool_page",
        "image_embeddings",
        ["model_version", "created_at", "asset_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_support_image_embeddings_pool_page", table_name="image_embeddings", schema=SCHEMA)
    op.drop_column("comparison_jobs", "device_id", schema=SCHEMA)
    op.drop_table("search_jobs", schema=SCHEMA)
    op.drop_table("worker_devices", schema=SCHEMA)
