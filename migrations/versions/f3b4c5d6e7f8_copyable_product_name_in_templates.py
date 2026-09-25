"""make the product name copyable (<code>) in the stored Fix / new-order templates

Stored template bodies override the code defaults, so the default change alone never
reached existing rows.

Revision ID: f3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-25
"""

from alembic import op

revision = "f3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None

KEYS = "('designer_new_order', 'designer_urgent_fix', 'admin_new_fix')"
OLD = "<b>Sản phẩm:</b> {{product_name}}"
NEW = "<b>Sản phẩm:</b> <code>{{product_name}}</code>"


def _swap(src: str, dst: str) -> None:
    op.get_bind().exec_driver_sql(
        f"UPDATE telegram_message_templates SET body = replace(body, %s, %s) WHERE template_key IN {KEYS}",
        (src, dst),
    )


def upgrade() -> None:
    _swap(OLD, NEW)


def downgrade() -> None:
    _swap(NEW, OLD)
