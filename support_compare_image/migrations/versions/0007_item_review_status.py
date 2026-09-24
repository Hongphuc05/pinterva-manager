"""human review state for comparison items (localhost review flow)"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_item_review_status"
down_revision: str | None = "0006_active_compare_job_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"
CONSTRAINT = "ck_support_compare_item_review_status"


def upgrade() -> None:
    op.add_column("comparison_items", sa.Column("review_status", sa.String(length=24), nullable=True), schema=SCHEMA)
    op.add_column("comparison_items", sa.Column("selected_candidate_id", sa.UUID(as_uuid=True), nullable=True), schema=SCHEMA)
    op.add_column("comparison_items", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)
    op.create_check_constraint(
        CONSTRAINT,
        "comparison_items",
        "review_status IS NULL OR review_status IN "
        "('pending_review', 'selected_duplicate', 'ai_wrong', 'no_match')",
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.comparison_items SET review_status = "
        "CASE WHEN is_duplicate IS TRUE THEN 'pending_review' ELSE 'no_match' END "
        "WHERE processing_status = 'completed'"
    )
    op.create_index(
        "ix_support_compare_comparison_items_review",
        "comparison_items",
        ["review_status", "run_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_support_compare_comparison_items_review", table_name="comparison_items", schema=SCHEMA)
    op.drop_constraint(CONSTRAINT, "comparison_items", schema=SCHEMA, type_="check")
    op.drop_column("comparison_items", "reviewed_at", schema=SCHEMA)
    op.drop_column("comparison_items", "selected_candidate_id", schema=SCHEMA)
    op.drop_column("comparison_items", "review_status", schema=SCHEMA)
