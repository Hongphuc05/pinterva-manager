"""add support classification attribution to orders

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("support_classified_by_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("support_classified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_support_classified_by_id_users",
        "orders",
        "users",
        ["support_classified_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_orders_support_classified_by_id",
        "orders",
        ["support_classified_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_support_classified_by_id", table_name="orders")
    op.drop_constraint(
        "fk_orders_support_classified_by_id_users",
        "orders",
        type_="foreignkey",
    )
    op.drop_column("orders", "support_classified_at")
    op.drop_column("orders", "support_classified_by_id")
