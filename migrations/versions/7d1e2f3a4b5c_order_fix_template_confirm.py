"""orders.fix_template_confirm: Printerval's "Đổi template" question and the Admin's answer

Revision ID: 7d1e2f3a4b5c
Revises: 3b9c9494a1a9
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7d1e2f3a4b5c"
down_revision = "3b9c9494a1a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("fix_template_confirm", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "fix_template_confirm")
