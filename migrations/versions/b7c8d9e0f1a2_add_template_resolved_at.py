"""record when Admin resolves a missing template report

Revision ID: b7c8d9e0f1a2
Revises: a2b3c4d5e6f7
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op


revision = "b7c8d9e0f1a2"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("template_resolved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "template_resolved_at")
