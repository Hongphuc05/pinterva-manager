"""store recoverable administrator-managed user passwords

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "7b8c9d0e1f2a"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_ciphertext")
