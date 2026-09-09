"""add order fix approval and previous note outsource fields

Revision ID: 1a2b3c4d5e6f
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09 21:05:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '1a2b3c4d5e6f'
down_revision = ('e7f8a9b0c1d2', 'f6a7b8c9d0e1')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'orders',
        sa.Column(
            'fix_approved_by_admin',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.add_column(
        'orders',
        sa.Column('previous_note_outsource', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('orders', 'previous_note_outsource')
    op.drop_column('orders', 'fix_approved_by_admin')
