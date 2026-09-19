"""add suppress_note_outsource_for_designer flag to orders

When Admin resolves a missing-template report, the note_outsource field
(Printerval QC feedback) must not be shown to the Designer during that
resolution cycle. This flag is set to True on resolve and cleared back to
False when the order is next synced from the platform or when note_outsource
is updated via normal admin flows.

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "suppress_note_outsource_for_designer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "suppress_note_outsource_for_designer")
