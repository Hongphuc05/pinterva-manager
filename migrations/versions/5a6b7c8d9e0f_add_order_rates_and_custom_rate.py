"""add order rates to platforms and custom_rate to orders

Revision ID: 5a6b7c8d9e0f
Revises: f1a2b3c4d5e
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5a6b7c8d9e0f"
down_revision: str | None = "f1a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platforms",
        sa.Column(
            "standard_order_rate",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("40000"),
        ),
    )
    op.add_column(
        "platforms",
        sa.Column(
            "duplicate_order_rate",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("40000"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "custom_rate",
            sa.Integer(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "custom_rate")
    op.drop_column("platforms", "duplicate_order_rate")
    op.drop_column("platforms", "standard_order_rate")
