"""add duplicate check status to orders

Revision ID: ea2b3c4d5e6f
Revises: cf1a2b3c4d5e
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ea2b3c4d5e6f"
down_revision: str = "cf1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "duplicate_check_status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'uncheck'"),
        ),
    )
    op.create_check_constraint(
        "ck_orders_duplicate_check_status",
        "orders",
        "duplicate_check_status IN ('uncheck', 'duplicate', 'non_duplicate')",
    )
    op.execute(
        sa.text(
            "UPDATE orders SET duplicate_check_status = 'duplicate' WHERE work_domain = 'duplicate'"
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_duplicate_check_status", "orders", type_="check")
    op.drop_column("orders", "duplicate_check_status")
