"""add normalized product_skus to orders

Revision ID: 6a7b8c9d0e1f
Revises: 1c2d3e4f5a6b
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6a7b8c9d0e1f"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("product_skus", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_column("orders", "template_jobs")
    op.drop_column("orders", "has_template")


def downgrade() -> None:
    op.add_column("orders", sa.Column("has_template", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("orders", sa.Column("template_jobs", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.drop_column("orders", "product_skus")
