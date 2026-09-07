"""add template_jobs to orders

Revision ID: 5e912a789bc0
Revises: 4d849c8b19ce
Create Date: 2026-09-08 00:45:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '5e912a789bc0'
down_revision = '4d849c8b19ce'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('template_jobs', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'template_jobs')
