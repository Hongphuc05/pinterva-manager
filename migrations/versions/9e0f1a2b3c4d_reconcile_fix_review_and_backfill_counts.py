"""reconcile legacy rejected Fix rows and seed their visible Fix count

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9e0f1a2b3c4d"
down_revision: str | None = "8d9e0f1a2b3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical rows do not have an exact count because older scheduled syncs
    # did not write a Fix event. A row that is/was in the Fix workflow has at
    # least one confirmed Printerval return, while future transitions are counted
    # exactly by application code.
    op.execute(
        sa.text(
            """
            UPDATE orders
            SET fix_return_count = 1
            WHERE fix_return_count = 0
              AND (
                state IN ('REVISION', 'REVISION_REQUESTED', 'FIX')
                OR fix_approved_by_admin = true
                OR fix_rejected_by_admin = true
                OR lower(coalesce(printerval_status, '')) = 'fix'
              )
            """
        )
    )
    # Before the reject endpoint was fixed, it wrote REVISION locally after it
    # had already requested Review on Printerval. Repair only rows where that
    # remote Review state is confirmed.
    op.execute(
        sa.text(
            """
            UPDATE orders
            SET state = 'QC_PENDING', status_changed_at = now()
            WHERE state IN ('REVISION', 'FIX')
              AND fix_rejected_by_admin = true
              AND lower(coalesce(printerval_status, '')) = 'review'
            """
        )
    )


def downgrade() -> None:
    # State/count repair is intentionally data-preserving and not reversible.
    pass
