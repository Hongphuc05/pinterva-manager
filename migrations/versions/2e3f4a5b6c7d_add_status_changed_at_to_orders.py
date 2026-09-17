"""add status_changed_at to orders

Revision ID: 2e3f4a5b6c7d
Revises: c72d1e4f5a6b
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2e3f4a5b6c7d"
down_revision: str = "c72d1e4f5a6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE orders SET status_changed_at = created_at WHERE status_changed_at IS NULL")


def downgrade() -> None:
    op.drop_column("orders", "status_changed_at")
