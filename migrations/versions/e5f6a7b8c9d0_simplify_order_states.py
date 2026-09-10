"""simplify order states to 7 basic states

Revision ID: e5f6a7b8c9d0
Revises: 9c0d1e2f3a4b
Create Date: 2026-09-08 23:14:00.000000

"""
from alembic import op

revision = 'e5f6a7b8c9d0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE orders SET state = 'OPEN' WHERE state IN (
            'DISCOVERED', 'CLAIMED_IMPORTED', 'OPEN_FOR_ALLOCATION',
            'ASSIGNMENT_PENDING_APPROVAL', 'REASSIGNMENT_REQUIRED'
        )
    """)
    op.execute("UPDATE orders SET state = 'IN_PROGRESS' WHERE state = 'ASSIGNED'")
    op.execute("""
        UPDATE orders SET state = 'QC_PENDING' WHERE state IN (
            'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE'
        )
    """)
    op.execute("UPDATE orders SET state = 'REVISION' WHERE state = 'REVISION_REQUESTED'")
    op.execute("UPDATE orders SET state = 'DONE' WHERE state = 'SKIPPED'")


def downgrade() -> None:
    pass
