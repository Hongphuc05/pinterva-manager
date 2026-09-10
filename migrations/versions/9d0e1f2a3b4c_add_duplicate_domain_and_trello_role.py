"""add duplicate work domain and designer trello role

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("work_domain", sa.String(length=32), nullable=False, server_default="standard"),
    )
    op.create_check_constraint(
        "ck_orders_work_domain", "orders", "work_domain IN ('standard', 'duplicate')"
    )
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role", "users", "role IN ('admin', 'designer', 'designer-trello')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", "role IN ('admin', 'designer')")
    op.drop_constraint("ck_orders_work_domain", "orders", type_="check")
    op.drop_column("orders", "work_domain")
