"""add duplicate board cross-designer drag setting

Revision ID: ab1c2d3e4f5a
Revises: 9d0e1f2a3b4c
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "ab1c2d3e4f5a"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "platforms",
        sa.Column(
            "duplicate_board_cross_designer_drag_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("platforms", "duplicate_board_cross_designer_drag_enabled")
