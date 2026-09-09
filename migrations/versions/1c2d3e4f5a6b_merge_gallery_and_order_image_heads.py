"""merge gallery bridge and order image migration heads

Revision ID: 1c2d3e4f5a6b
Revises: 0f9e1d2c3b4a, 8f1a2b3c4d5e
Create Date: 2026-09-10
"""

from collections.abc import Sequence

revision: str = "1c2d3e4f5a6b"
down_revision: tuple[str, str] = ("0f9e1d2c3b4a", "8f1a2b3c4d5e")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
