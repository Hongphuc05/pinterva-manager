"""add CopyImage gallery bridge token to platforms

Revision ID: 0f9e1d2c3b4a
Revises: e7f8a9b0c1d2
Create Date: 2026-09-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f9e1d2c3b4a"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("platforms", sa.Column("gallery_bridge_token_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("platforms", "gallery_bridge_token_hash")
