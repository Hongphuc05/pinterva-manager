"""merge printerval_designer_option and source_files branches

Revision ID: 5170b6101e92
Revises: 3b4c5d6e7f8a, 9c0d1e2f3a4b
Create Date: 2026-09-08 19:05:12.643260

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '5170b6101e92'
down_revision = ('3b4c5d6e7f8a', '9c0d1e2f3a4b')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
