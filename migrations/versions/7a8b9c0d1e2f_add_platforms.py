"""add platforms and platform_id to orders, users, batches

Revision ID: 7a8b9c0d1e2f
Revises: 5e912a789bc0
Create Date: 2026-09-08 01:15:00.000000

"""
import uuid
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '7a8b9c0d1e2f'
down_revision = '5e912a789bc0'
branch_labels = None
depends_on = None

DEFAULT_PLATFORM_ID = str(uuid.UUID('11111111-1111-1111-1111-111111111111'))

def upgrade() -> None:
    op.create_table(
        'platforms',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('account_username', sa.String(length=128), nullable=False),
        sa.Column('account_password', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    op.add_column('users', sa.Column('platform_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_users_platform_id', 'users', 'platforms', ['platform_id'], ['id'])

    op.add_column('batches', sa.Column('platform_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_batches_platform_id', 'batches', 'platforms', ['platform_id'], ['id'])

    op.add_column('orders', sa.Column('platform_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_orders_platform_id', 'orders', 'platforms', ['platform_id'], ['id'])

    # Seed default platform & backfill existing rows
    op.execute(
        f"INSERT INTO platforms (id, name, account_username, is_active) "
        f"VALUES ('{DEFAULT_PLATFORM_ID}', 'Nền tảng Mặc định (Acc Mẹ 1)', 'main_admin@printerval.com', true) "
        f"ON CONFLICT DO NOTHING"
    )
    op.execute(f"UPDATE users SET platform_id = '{DEFAULT_PLATFORM_ID}' WHERE platform_id IS NULL")
    op.execute(f"UPDATE batches SET platform_id = '{DEFAULT_PLATFORM_ID}' WHERE platform_id IS NULL")
    op.execute(f"UPDATE orders SET platform_id = '{DEFAULT_PLATFORM_ID}' WHERE platform_id IS NULL")


def downgrade() -> None:
    op.drop_constraint('fk_orders_platform_id', 'orders', type_='foreignkey')
    op.drop_column('orders', 'platform_id')
    op.drop_constraint('fk_batches_platform_id', 'batches', type_='foreignkey')
    op.drop_column('batches', 'platform_id')
    op.drop_constraint('fk_users_platform_id', 'users', type_='foreignkey')
    op.drop_column('users', 'platform_id')
    op.drop_table('platforms')
