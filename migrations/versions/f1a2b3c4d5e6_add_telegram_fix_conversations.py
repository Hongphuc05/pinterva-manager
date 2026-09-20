"""track Telegram Fix messages for cleanup

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_fix_conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("root_message_id", sa.Integer(), nullable=False),
        sa.Column("transient_message_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("cleaned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "chat_id", "root_message_id", name="uq_telegram_fix_conversation_root"),
    )
    op.create_index("ix_telegram_fix_conversations_order_id", "telegram_fix_conversations", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_telegram_fix_conversations_order_id", table_name="telegram_fix_conversations")
    op.drop_table("telegram_fix_conversations")
