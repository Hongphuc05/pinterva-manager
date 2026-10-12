"""username unique per platform (not globally); FK policy for hard-deleting a user

Two platforms may now use the same username/support-take designer name without colliding
(each is scoped to its own Acc Mẹ). The FK columns that reference users.id are split in two:

- "this row IS the user's own record" (an Assignment linking them to an order, a note they
  wrote, a decision they made...): ON DELETE CASCADE, so a hard delete of the user also
  removes these.
- "this row is about something else (an Order, a shared template...) and the user merely
  acted on it": ON DELETE SET NULL, so hard-deleting the user keeps that record (Order
  audit trail, template) intact, just loses the "who" attribution. PaymentBatch/Order.paid_by_id
  already SET NULL from earlier migrations and are untouched here — they also keep a plain-text
  name snapshot, so payment history stays readable even after the user row is gone.

Revision ID: f5d6e7f8a9b0
Revises: f4c5d6e7f8a9
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "f5d6e7f8a9b0"
down_revision = "f4c5d6e7f8a9"
branch_labels = None
depends_on = None

CASCADE_FKS = [
    ("assignments", "designer_id"),
    ("order_work_notes", "author_id"),
    ("approval_decisions", "actor_id"),
    ("printerval_assignment_requests", "internal_designer_id"),
    ("finance_notes", "designer_id"),
    ("finance_notes", "author_id"),
    ("telegram_action_logs", "actor_id"),
    ("telegram_configuration_audits", "actor_id"),
    ("telegram_configuration_audits", "target_user_id"),
]

SET_NULL_FKS = [
    ("workflow_events", "actor_id"),
    ("orders", "processing_lock_owner_id"),
    ("orders", "template_missing_reported_by_id"),
    ("sync_jobs", "created_by_id"),
    ("telegram_message_templates", "updated_by_id"),
]

_FIND_FK_NAME = sa.text(
    """
    SELECT tc.constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
      AND tc.table_name = :table_name AND kcu.column_name = :column_name
    """
)


def _retarget_fk(table: str, column: str, ondelete: str) -> None:
    conn = op.get_bind()
    name = conn.execute(_FIND_FK_NAME, {"table_name": table, "column_name": column}).scalar()
    if name is None:
        raise RuntimeError(f"no existing FK constraint found for {table}.{column} -> users.id")
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column in CASCADE_FKS:
        _retarget_fk(table, column, "CASCADE")
    for table, column in SET_NULL_FKS:
        _retarget_fk(table, column, "SET NULL")

    op.drop_constraint("users_username_key", "users", type_="unique")
    op.create_unique_constraint("uq_users_platform_id_username", "users", ["platform_id", "username"])


def downgrade() -> None:
    op.drop_constraint("uq_users_platform_id_username", "users", type_="unique")
    op.create_unique_constraint("users_username_key", "users", ["username"])

    for table, column in SET_NULL_FKS:
        _retarget_fk(table, column, "NO ACTION")
    for table, column in CASCADE_FKS:
        _retarget_fk(table, column, "NO ACTION")
