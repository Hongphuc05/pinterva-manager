"""persist duplicate board card insertion positions

Revision ID: 7c8d9e0f1a2b
Revises: 6b7c8d9e0f1a
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c8d9e0f1a2b"
down_revision: str | None = "6b7c8d9e0f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("duplicate_board_position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "duplicate_board_position")
