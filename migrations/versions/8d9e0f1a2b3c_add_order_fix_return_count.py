"""track the number of Printerval Fix returns per order

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8d9e0f1a2b3c"
down_revision: str | None = "7c8d9e0f1a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("fix_return_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("orders", "fix_return_count")
