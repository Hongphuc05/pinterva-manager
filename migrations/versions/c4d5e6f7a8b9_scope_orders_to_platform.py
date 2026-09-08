"""scope external order IDs to their Printerval platform

Revision ID: c4d5e6f7a8b9
Revises: b8c9d0e1f2a3
Create Date: 2026-09-08
"""

from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

DEFAULT_PLATFORM_ID = "11111111-1111-1111-1111-111111111111"


def upgrade() -> None:
    # Legacy rows predate multi-platform support and belong to the original mother
    # account. Leaving them NULL made them appear in every platform's order list.
    op.execute(
        "UPDATE orders SET platform_id = "
        f"'{DEFAULT_PLATFORM_ID}'::uuid WHERE platform_id IS NULL"
    )
    op.drop_constraint("orders_external_order_id_key", "orders", type_="unique")
    op.create_unique_constraint(
        "uq_orders_platform_external_id",
        "orders",
        ["platform_id", "external_order_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_orders_platform_external_id", "orders", type_="unique")
    op.create_unique_constraint("orders_external_order_id_key", "orders", ["external_order_id"])
