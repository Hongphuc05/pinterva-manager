"""add team_outsource to platforms

Revision ID: 9c1d2e3f4a5b
Revises: 7a8b9c0d1e2f
Create Date: 2026-09-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '9c1d2e3f4a5b'
down_revision = '7a8b9c0d1e2f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('platforms', sa.Column('team_outsource', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('platforms', 'team_outsource')
