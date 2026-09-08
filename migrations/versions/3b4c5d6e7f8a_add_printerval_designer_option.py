"""add printerval_designer_option to users

Revision ID: 3b4c5d6e7f8a
Revises: 2a3b4c5d6e7f
Create Date: 2026-09-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '3b4c5d6e7f8a'
down_revision = '2a3b4c5d6e7f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('printerval_designer_option', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'printerval_designer_option')
