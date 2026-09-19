"""add durable Telegram deadline alert fields

Revision ID: b3c4d5e6f7a8
Revises: b2c3d4e5f6a7
"""

import sqlalchemy as sa
from alembic import op

revision = "b3c4d5e6f7a8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("fix_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("deadline_overdue_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("template_missing_notified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "template_missing_notified_at")
    op.drop_column("orders", "deadline_overdue_notified_at")
    op.drop_column("orders", "fix_deadline_at")
