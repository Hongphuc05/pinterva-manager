"""add Support Telegram audiences and duplicate-review templates

Revision ID: f2a3b4c5d6e7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-24
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


SUPPORT_TEMPLATES = [
    {
        "template_key": "support_duplicate_new_candidate",
        "audience": "support",
        "body": (
            "🆕 <b>ĐƠN MỚI CẦN KIỂM TRA TRÙNG</b>\n"
            "📦 Mã đơn: <code>{{order_code}}</code>\n"
            "👕 Sản phẩm: {{product_name}}\n"
            "Ảnh mới"
        ),
    },
    {
        "template_key": "support_duplicate_match_candidate",
        "audience": "support",
        "body": (
            "🗂 <b>ẢNH ĐÃ CÓ TRONG KHO LỊCH SỬ</b>\n"
            "📦 Mã đơn cũ: <code>{{matched_order_code}}</code>\n"
            "👕 Sản phẩm cũ: {{matched_product_name}}\n"
            "📊 Similarity: <code>{{similarity}}</code>\n"
            "🏷 Classifier: <code>{{classifier}}</code>\n\n"
            "Đây có phải là đơn trùng không?"
        ),
    },
]


def upgrade() -> None:
    op.drop_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        "audience IN ('designer', 'admin', 'support')",
    )

    template_table = sa.table(
        "telegram_message_templates",
        sa.column("id", sa.UUID()),
        sa.column("template_key", sa.String(length=64)),
        sa.column("audience", sa.String(length=16)),
        sa.column("body", sa.Text()),
        sa.column("active", sa.Boolean()),
        sa.column("version", sa.Integer()),
    )
    op.bulk_insert(
        template_table,
        [
            {
                "id": uuid4(),
                "template_key": item["template_key"],
                "audience": item["audience"],
                "body": item["body"],
                "active": True,
                "version": 1,
            }
            for item in SUPPORT_TEMPLATES
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM telegram_message_templates "
            "WHERE template_key IN "
            "('support_duplicate_new_candidate', 'support_duplicate_match_candidate')"
        )
    )
    op.drop_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        "audience IN ('designer', 'admin')",
    )
