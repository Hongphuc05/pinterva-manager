"""add printerval_status mirror to orders and platform_sync_state table

Revision ID: 2a3b4c5d6e7f
Revises: 9c1d2e3f4a5b
Create Date: 2026-09-08 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2a3b4c5d6e7f'
down_revision = '9c1d2e3f4a5b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('printerval_status', sa.String(length=16), nullable=True))
    op.add_column(
        'orders', sa.Column('printerval_status_synced_at', sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        'platform_sync_state',
        sa.Column('platform_id', sa.UUID(), nullable=False),
        sa.Column('is_running', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('last_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_result', postgresql.JSONB(), nullable=True),
        sa.Column('last_error', sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint('platform_id'),
        sa.ForeignKeyConstraint(['platform_id'], ['platforms.id'], name='fk_platform_sync_state_platform_id'),
    )


def downgrade() -> None:
    op.drop_table('platform_sync_state')
    op.drop_column('orders', 'printerval_status_synced_at')
    op.drop_column('orders', 'printerval_status')
