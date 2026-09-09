"""cache Printerval Designer options per platform

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platforms", sa.Column("printerval_designer_options", postgresql.JSONB(), nullable=True))
    op.add_column("platforms", sa.Column("printerval_status_options", postgresql.JSONB(), nullable=True))
    op.add_column("platforms", sa.Column("printerval_options_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("platforms", "printerval_options_synced_at")
    op.drop_column("platforms", "printerval_status_options")
    op.drop_column("platforms", "printerval_designer_options")
