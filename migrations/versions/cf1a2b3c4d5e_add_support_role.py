"""add support role to users

Revision ID: cf1a2b3c4d5e
Revises: 4b5c6d7e8f9a
Create Date: 2026-09-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cf1a2b3c4d5e"
down_revision: str = "4b5c6d7e8f9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('admin', 'designer', 'designer-trello', 'support')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('admin', 'designer', 'designer-trello')"
    )
