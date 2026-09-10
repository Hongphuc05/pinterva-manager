"""add source_files and order_links to orders

Revision ID: 9c0d1e2f3a4b
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-08 19:05:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '9c0d1e2f3a4b'
down_revision = '7a8b9c0d1e2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('sku_image_url', sa.String(length=1024), nullable=True))
    op.add_column('orders', sa.Column('external_order_url', sa.String(length=1024), nullable=True))
    op.add_column('orders', sa.Column('source_files', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('orders', sa.Column('source_download_all_url', sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'source_download_all_url')
    op.drop_column('orders', 'source_files')
    op.drop_column('orders', 'external_order_url')
    op.drop_column('orders', 'sku_image_url')
