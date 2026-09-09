"""add product_image_urls to orders

Revision ID: 8f1a2b3c4d5e
Revises: 1a2b3c4d5e6f
Create Date: 2026-09-10 00:15:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '8f1a2b3c4d5e'
down_revision = '1a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'orders',
        sa.Column(
            'product_image_urls',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('orders', 'product_image_urls')
