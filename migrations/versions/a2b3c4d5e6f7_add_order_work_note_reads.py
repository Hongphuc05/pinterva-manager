"""track the latest work note seen by each order operator

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op


revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_work_note_reads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "user_id", name="uq_order_work_note_read_user"),
    )
    op.create_index("ix_order_work_note_reads_order_id", "order_work_note_reads", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_order_work_note_reads_order_id", table_name="order_work_note_reads")
    op.drop_table("order_work_note_reads")
