"""orders.fix_dispute: the Admin's "Báo fix không đúng" sent to Printerval and its arbitration

Revision ID: f6cc66869410
Revises: 7d1e2f3a4b5c
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f6cc66869410"
down_revision = "7d1e2f3a4b5c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("fix_dispute", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "fix_dispute")
