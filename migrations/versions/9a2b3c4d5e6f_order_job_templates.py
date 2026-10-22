"""orders.job_templates: the templates of a Printerval job (image, PSD link, note)

Revision ID: 9a2b3c4d5e6f
Revises: f6cc66869410
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9a2b3c4d5e6f"
down_revision = "f6cc66869410"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("job_templates", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "job_templates")
