"""backfill missing order tab timestamps

Revision ID: 6b7c8d9e0f1a
Revises: 5a6b7c8d9e0f
Create Date: 2026-09-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6b7c8d9e0f1a"
down_revision: str | None = "5a6b7c8d9e0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rows imported after the original status_changed_at migration were missing
    # the initial tab-entry timestamp. created_at is their audited import time.
    op.execute("UPDATE orders SET status_changed_at = created_at WHERE status_changed_at IS NULL")


def downgrade() -> None:
    # A data backfill is intentionally irreversible.
    pass
