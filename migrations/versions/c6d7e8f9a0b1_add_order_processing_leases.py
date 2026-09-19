"""add short-lived processing lease columns to orders

Revision ID: c6d7e8f9a0b1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-20
"""

import sqlalchemy as sa
from alembic import op

revision = "c6d7e8f9a0b1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("processing_lock_owner_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_orders_processing_lock_owner_id_users", "orders", "users", ["processing_lock_owner_id"], ["id"]
    )
    op.add_column("orders", sa.Column("processing_lock_acquired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("processing_lock_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("processing_lock_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_orders_processing_lock_expires_at", "orders", ["processing_lock_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_processing_lock_expires_at", table_name="orders")
    op.drop_constraint("fk_orders_processing_lock_owner_id_users", "orders", type_="foreignkey")
    op.drop_column("orders", "processing_lock_expires_at")
    op.drop_column("orders", "processing_lock_heartbeat_at")
    op.drop_column("orders", "processing_lock_acquired_at")
    op.drop_column("orders", "processing_lock_owner_id")
