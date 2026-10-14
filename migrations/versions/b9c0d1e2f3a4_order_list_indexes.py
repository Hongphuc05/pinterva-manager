"""indexes for the order list: assignments / assignment requests by order, orders by platform

Revision ID: b9c0d1e2f3a4
Revises: f5d6e7f8a9b0
"""

from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "f5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_assignments_order_status ON assignments (order_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pa_requests_order_created "
        "ON printerval_assignment_requests (order_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_platform_created ON orders (platform_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_platform_created")
    op.execute("DROP INDEX IF EXISTS ix_pa_requests_order_created")
    op.execute("DROP INDEX IF EXISTS ix_assignments_order_status")
