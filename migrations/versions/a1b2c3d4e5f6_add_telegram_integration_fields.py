"""add telegram integration fields to users and create telegram_action_logs table

Revision ID: a1b2c3d4e5f6
Revises: 9e0f1a2b3c4d
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "9e0f1a2b3c4d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add Telegram columns to users
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(length=128), nullable=True))
    op.add_column("users", sa.Column("telegram_link_code", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("telegram_link_code_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "telegram_notifications_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"], unique=False)
    op.create_index("ix_users_telegram_link_code", "users", ["telegram_link_code"], unique=True)

    # 2. Create telegram_action_logs table
    op.create_table(
        "telegram_action_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("callback_token", sa.String(length=64), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_action_logs_callback_token",
        "telegram_action_logs",
        ["callback_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_action_logs_callback_token", table_name="telegram_action_logs")
    op.drop_table("telegram_action_logs")
    op.drop_index("ix_users_telegram_link_code", table_name="users")
    op.drop_index("ix_users_telegram_chat_id", table_name="users")
    op.drop_column("users", "telegram_notifications_enabled")
    op.drop_column("users", "telegram_link_code_expires_at")
    op.drop_column("users", "telegram_link_code")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_chat_id")
