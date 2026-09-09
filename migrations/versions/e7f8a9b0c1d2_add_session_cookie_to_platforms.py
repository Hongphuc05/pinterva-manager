"""add session_cookie to platforms

Revision ID: e7f8a9b0c1d2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09 13:19:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('platforms', sa.Column('session_cookie', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('platforms', 'session_cookie')
