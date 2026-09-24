"""add database-backed duplicate comparison runs and candidates"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_comparison_runs"
down_revision: str | None = "0002_image_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("platform_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("classifier_version", sa.String(length=64), nullable=False),
        sa.Column("run_status", sa.String(length=16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("baseline_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("requested_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("promote_new_images", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('review', 'waiting', 'manual')",
            name="ck_support_compare_comparison_source_kind",
        ),
        sa.CheckConstraint(
            "run_status IN ('running', 'completed', 'failed', 'stopped')",
            name="ck_support_compare_comparison_run_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_comparison_runs_status",
        "comparison_runs",
        ["run_status", "source_kind"],
        schema=SCHEMA,
    )

    op.create_table(
        "comparison_items",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=False),
        sa.Column("product_name", sa.String(length=512), nullable=True),
        sa.Column("source_state", sa.String(length=32), nullable=True),
        sa.Column("source_printerval_status", sa.String(length=32), nullable=True),
        sa.Column("source_order_version", sa.Integer(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("image_url_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", postgresql.BYTEA(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("phash", sa.String(length=128), nullable=True),
        sa.Column("color_l", sa.Float(), nullable=True),
        sa.Column("color_a", sa.Float(), nullable=True),
        sa.Column("color_b", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=True),
        sa.Column("processing_status", sa.String(length=16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("pool_promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pool_promotion_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], [f"{SCHEMA}.comparison_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "run_id",
            "order_id",
            "image_url_sha256",
            "model_version",
            name="uq_support_compare_comparison_item_source",
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'processing', 'completed', 'failed', 'skipped')",
            name="ck_support_compare_comparison_item_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_comparison_items_order",
        "comparison_items",
        ["platform_id", "order_id", "processing_status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_comparison_items_run_status",
        "comparison_items",
        ["run_id", "processing_status"],
        schema=SCHEMA,
    )

    op.create_table(
        "comparison_candidates",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("comparison_item_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("historical_job_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("historical_asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("matched_external_order_id", sa.String(length=128), nullable=True),
        sa.Column("matched_product_name", sa.String(length=512), nullable=True),
        sa.Column("matched_image_url", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("visual_similarity", sa.Float(), nullable=False),
        sa.Column("phash_distance", sa.Integer(), nullable=True),
        sa.Column("ssim", sa.Float(), nullable=True),
        sa.Column("color_delta_e", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("classifier_version", sa.String(length=64), nullable=False),
        sa.Column("decision_status", sa.String(length=24), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decided_by_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["comparison_item_id"],
            [f"{SCHEMA}.comparison_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["historical_job_id"],
            [f"{SCHEMA}.historical_jobs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["historical_asset_id"],
            [f"{SCHEMA}.image_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "comparison_item_id",
            "historical_asset_id",
            "classifier_version",
            name="uq_support_compare_candidate_asset_classifier",
        ),
        sa.CheckConstraint(
            "decision_status IN ('pending', 'duplicate', 'non_duplicate', 'superseded')",
            name="ck_support_compare_candidate_decision_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_support_compare_candidates_review_queue",
        "comparison_candidates",
        ["classification", "decision_status", "telegram_notified_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("comparison_candidates", schema=SCHEMA)
    op.drop_table("comparison_items", schema=SCHEMA)
    op.drop_table("comparison_runs", schema=SCHEMA)
