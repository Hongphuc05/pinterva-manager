"""add designer note and missing-template queue

Revision ID: c72d1e4f5a6b
Revises: ab1c2d3e4f5a
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

revision = "c72d1e4f5a6b"
down_revision = "ab1c2d3e4f5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("designer_note", sa.Text(), nullable=False, server_default=""))
    op.add_column("orders", sa.Column("template_missing", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("orders", sa.Column("template_missing_reported_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("template_missing_reported_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_orders_template_missing_reported_by_id_users",
        "orders", "users", ["template_missing_reported_by_id"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_orders_template_missing_reported_by_id_users", "orders", type_="foreignkey")
    op.drop_column("orders", "template_missing_reported_by_id")
    op.drop_column("orders", "template_missing_reported_at")
    op.drop_column("orders", "template_missing")
    op.drop_column("orders", "designer_note")
