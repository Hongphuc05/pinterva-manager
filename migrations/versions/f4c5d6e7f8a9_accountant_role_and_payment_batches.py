"""accountant role, payment_batches history, and rebuild the history of orders paid before it

Revision ID: f4c5d6e7f8a9
Revises: f3b4c5d6e7f8
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4c5d6e7f8a9"
down_revision = "f3b4c5d6e7f8"
branch_labels = None
depends_on = None

ROLES_WITH = "role IN ('admin', 'designer', 'designer-trello', 'support', 'accountant')"
ROLES_WITHOUT = "role IN ('admin', 'designer', 'designer-trello', 'support')"


def upgrade() -> None:
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", ROLES_WITH)

    op.create_table(
        "payment_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("platform_id", sa.UUID(), nullable=True),
        sa.Column("paid_by_id", sa.UUID(), nullable=True),
        sa.Column("paid_by_name", sa.String(length=255), nullable=False),
        sa.Column("paid_by_role", sa.String(length=32), nullable=True),
        sa.Column("designer_id", sa.UUID(), nullable=True),
        sa.Column("designer_name", sa.String(length=255), nullable=False),
        sa.Column("order_count", sa.Integer(), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source IN ('payment', 'backfill')", name="ck_payment_batches_source"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"]),
        sa.ForeignKeyConstraint(["paid_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["designer_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_batches_platform_paid_at", "payment_batches", ["platform_id", "paid_at"])
    op.create_index("ix_payment_batches_designer_id", "payment_batches", ["designer_id"])

    # Rebuild the history of the orders paid so far. The credit rules (who gets credited
    # for an order) only exist in application code, so reuse it rather than copy it here.
    # A fresh database has no paid order: skip, so replaying this revision later never runs
    # today's ORM models against an older schema.
    if op.get_bind().execute(sa.text("SELECT 1 FROM orders WHERE is_paid LIMIT 1")).first() is None:
        return

    from sqlalchemy.orm import Session

    from app.application.payments import backfill_payment_batches

    session = Session(bind=op.get_bind())
    try:
        backfill_payment_batches(session)
    finally:
        session.close()


def downgrade() -> None:
    op.drop_index("ix_payment_batches_designer_id", table_name="payment_batches")
    op.drop_index("ix_payment_batches_platform_paid_at", table_name="payment_batches")
    op.drop_table("payment_batches")
    op.execute("UPDATE users SET role = 'designer' WHERE role = 'accountant'")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.create_check_constraint("ck_users_role", "users", ROLES_WITHOUT)
