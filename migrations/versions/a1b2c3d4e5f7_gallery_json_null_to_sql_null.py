"""orders.product_image_urls: JSON null becomes SQL NULL

An order crawled without a gallery stored JSON ``null``; counting the gallery then failed and took the
whole order page down (HTTP 500).

Revision ID: a1b2c3d4e5f7
Revises: 9a2b3c4d5e6f
Create Date: 2026-10-22
"""

from alembic import op

revision = "a1b2c3d4e5f7"
down_revision = "9a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE orders SET product_image_urls = NULL WHERE jsonb_typeof(product_image_urls) = 'null'")


def downgrade() -> None:
    pass  # nothing to restore: JSON null and SQL NULL mean the same here
