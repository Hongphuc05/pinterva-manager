"""order_chat_messages, order_chat_reads and the chat cursor columns on orders

Revision ID: a8f3c2d1e0b9
Revises: f5d6e7f8a9b0
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a8f3c2d1e0b9"
down_revision = "f5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("chat_last_message_id", sa.BigInteger(), nullable=True))
    op.add_column("orders", sa.Column("chat_synced_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "order_chat_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("platform_id", sa.UUID(), nullable=True),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("fix_round", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("message_type", sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column("sender_type", sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column("sender_name", sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column("mine", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("content", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "image_urls", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("fix_reason_label", sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "external_id", name="uq_order_chat_message_external"),
    )
    op.create_index("ix_order_chat_messages_order_id", "order_chat_messages", ["order_id"])
    op.create_index("ix_order_chat_messages_platform_sent", "order_chat_messages", ["platform_id", "sent_at"])

    op.create_table(
        "order_chat_reads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("last_read_external_id", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "user_id", name="uq_order_chat_read_user"),
    )
    op.create_index("ix_order_chat_reads_order_id", "order_chat_reads", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_chat_reads")
    op.drop_table("order_chat_messages")
    op.drop_column("orders", "chat_synced_at")
    op.drop_column("orders", "chat_last_message_id")
