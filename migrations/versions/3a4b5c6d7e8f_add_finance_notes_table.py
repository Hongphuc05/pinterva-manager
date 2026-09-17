"""add finance_notes table

Revision ID: 3a4b5c6d7e8f
Revises: 2e3f4a5b6c7d
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3a4b5c6d7e8f"
down_revision: str = "2e3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finance_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("platform_id", sa.UUID(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=True),
        sa.Column("order_code", sa.String(length=64), nullable=True),
        sa.Column("designer_id", sa.UUID(), nullable=True),
        sa.Column("designer_name", sa.String(length=255), nullable=True),
        sa.Column("author_id", sa.UUID(), nullable=True),
        sa.Column("author_name", sa.String(length=255), nullable=False, server_default="Admin"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["designer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finance_notes_target_type", "finance_notes", ["target_type"])
    op.create_index("ix_finance_notes_order_id", "finance_notes", ["order_id"])
    op.create_index("ix_finance_notes_designer_id", "finance_notes", ["designer_id"])


def downgrade() -> None:
    op.drop_index("ix_finance_notes_designer_id", table_name="finance_notes")
    op.drop_index("ix_finance_notes_order_id", table_name="finance_notes")
    op.drop_index("ix_finance_notes_target_type", table_name="finance_notes")
    op.drop_table("finance_notes")
