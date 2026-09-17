"""add payment and review_submitted_at to orders

Revision ID: 4b5c6d7e8f9a
Revises: 3a4b5c6d7e8f
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b5c6d7e8f9a"
down_revision: str = "3a4b5c6d7e8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "is_paid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column(
            "paid_by_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column("review_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill review_submitted_at from status_changed_at or created_at for orders already in QC_PENDING/REVIEW/REVISION/DONE
    op.execute(
        """
        UPDATE orders
        SET review_submitted_at = COALESCE(status_changed_at, updated_at, created_at)
        WHERE state IN ('QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW', 'REVISION', 'REVISION_REQUESTED', 'FIX', 'DONE', 'CLAIMED_IMPORTED', 'COMPLETED')
          AND review_submitted_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("orders", "review_submitted_at")
    op.drop_column("orders", "paid_by_id")
    op.drop_column("orders", "paid_at")
    op.drop_column("orders", "is_paid")
