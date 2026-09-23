"""create the support duplicate-image backfill schema"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_support_compare_image"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("team_outsource", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("target_statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("run_status", sa.String(length=16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stored_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("preview_missing_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("malformed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_page_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "run_status IN ('running', 'completed', 'failed', 'stopped')",
            name="ck_support_compare_crawl_run_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_crawl_runs_status", "crawl_runs", ["run_status"], schema=SCHEMA
    )

    op.create_table(
        "crawl_checkpoints",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next_page_id", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_seen", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_stored", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("preview_missing_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("malformed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("api_total_count", sa.Integer(), nullable=True),
        sa.Column("api_page_count", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], [f"{SCHEMA}.crawl_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("run_id", "status", name="uq_support_compare_checkpoint_run_status"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_checkpoints_resume",
        "crawl_checkpoints",
        ["run_id", "completed", "next_page_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "crawl_errors",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("page_id", sa.Integer(), nullable=True),
        sa.Column("source_job_id", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], [f"{SCHEMA}.crawl_runs.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_crawl_errors_run",
        "crawl_errors",
        ["run_id", "status", "page_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "historical_jobs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("source_job_id", sa.String(length=128), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("team_outsource", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=True),
        sa.Column("product_name", sa.String(length=512), nullable=False),
        sa.Column("sku", sa.String(length=256), nullable=True),
        sa.Column("product_category", sa.String(length=256), nullable=True),
        sa.Column("note_outsource", sa.Text(), nullable=True),
        sa.Column("raw_preview_url", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("preview_source_path", sa.String(length=512), nullable=True),
        sa.Column("preview_missing", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("ingest_source", sa.String(length=32), nullable=False, server_default=sa.text("'historical_backfill'")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_run_id", sa.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"], [f"{SCHEMA}.crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "source_system", "source_job_id", name="uq_support_compare_historical_job_source_id"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_historical_jobs_status",
        "historical_jobs",
        ["status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_historical_jobs_external_code",
        "historical_jobs",
        ["external_order_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_historical_jobs_product_name",
        "historical_jobs",
        ["product_name"],
        schema=SCHEMA,
    )

    op.create_table(
        "image_assets",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_system", sa.String(length=64), nullable=False),
        sa.Column("url_sha256", sa.String(length=64), nullable=False),
        sa.Column("raw_url", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetch_status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_system", "url_sha256", name="uq_support_compare_image_asset_url"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_image_assets_fetch_status",
        "image_assets",
        ["fetch_status"],
        schema=SCHEMA,
    )

    op.create_table(
        "job_images",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(
            ["job_id"], [f"{SCHEMA}.historical_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], [f"{SCHEMA}.image_assets.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "job_id", "role", "position", name="uq_support_compare_job_image_role_position"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_job_images_asset", "job_images", ["asset_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("job_images", schema=SCHEMA)
    op.drop_table("image_assets", schema=SCHEMA)
    op.drop_table("historical_jobs", schema=SCHEMA)
    op.drop_table("crawl_errors", schema=SCHEMA)
    op.drop_table("crawl_checkpoints", schema=SCHEMA)
    op.drop_table("crawl_runs", schema=SCHEMA)
    # Keep the namespace and this migration tree's version table. Alembic updates
    # that table after the downgrade; dropping the schema here would make the
    # downgrade itself fail because `alembic_version` still exists.
