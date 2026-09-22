"""add Telegram routing, editable templates and configuration audit

Revision ID: e9f0a1b2c3d4
Revises: d7e8f9a0b1c2
Create Date: 2026-09-22
"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e9f0a1b2c3d4"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


DEFAULT_TEMPLATES = [
    {
        "template_key": "designer_new_order",
        "audience": "designer",
        "body": (
            "🎨 <b>BẠN CÓ ĐƠN HÀNG MỚI (ĐANG LÀM)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "⏰ <b>Hạn chót:</b> {{deadline}}\n"
            "📝 <b>Note Admin:</b> {{admin_note}}"
        ),
    },
    {
        "template_key": "designer_urgent_fix",
        "audience": "designer",
        "body": (
            "🚨 <b>CẢNH BÁO: ĐƠN CẦN SỬA GẤP (FIX)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "🔄 <b>Lần fix thứ:</b> #{{fix_count}}\n"
            "⏰ <b>Hạn sửa:</b> {{deadline}}\n"
            "📌 <b>Hướng dẫn từ Admin:</b> {{admin_note}}\n"
            "⚡ <i>Vui lòng vào tab <b>Cần sửa gấp</b> trên web để xử lý ngay!</i>"
        ),
    },
    {
        "template_key": "designer_payment",
        "audience": "designer",
        "body": (
            "💰 <b>THÔNG BÁO THANH TOÁN TIỀN CÔNG</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🎉 Admin vừa duyệt thanh toán tiền công cho bạn!\n"
            "📦 <b>Số lượng đơn:</b> {{order_count}} đơn\n"
            "💵 <b>Tổng tiền công:</b> <b>{{total_amount}}</b>\n"
            "📅 <b>Thời gian:</b> {{time}}\n\n"
            "<i>Cảm ơn bạn đã nỗ lực! Chúc bạn làm việc hiệu quả và nhiều năng lượng!</i>"
        ),
    },
    {
        "template_key": "admin_new_fix",
        "audience": "admin",
        "body": (
            "⚠️ <b>CÓ ĐƠN FIX MỚI TỪ PLATFORM!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🔄 <b>Lần fix:</b> #{{fix_count}}\n"
            "📝 <b>Ghi chú từ QC:</b> {{qc_note}}\n\n"
            "👉 <i>Admin chọn thao tác xử lý bên dưới:</i>"
        ),
    },
    {
        "template_key": "admin_review_submitted",
        "audience": "admin",
        "body": (
            "📤 <b>DESIGNER VỪA NỘP BÀI (REVIEW)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👕 <b>Sản phẩm:</b> {{product_name}}\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🔗 <b>Link nộp:</b> {{submission_link}}\n"
            "⏱ <i>Hệ thống đang tự động đồng bộ Review lên Platform.</i>"
        ),
    },
    {
        "template_key": "admin_missing_template",
        "audience": "admin",
        "body": (
            "🚩 <b>DESIGNER BÁO THIẾU TEMP!</b>\n"
            "📦 <b>Mã đơn:</b> <code>{{order_code}}</code>\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "🕒 <b>Deadline:</b> {{deadline}}\n"
            "👉 Admin bổ sung temp/ghi chú để Designer tiếp tục làm."
        ),
    },
    {
        "template_key": "admin_excessive_fix",
        "audience": "admin",
        "body": (
            "🚨 <b>CẢNH BÁO CHẤT LƯỢNG (QC ALERT)!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Đơn <code>{{order_code}}</code> đã bị trả về Fix <b>lần thứ {{fix_count}}</b>!\n"
            "👤 <b>Designer phụ trách:</b> {{designer_name}}\n"
            "💡 <i>Gợi ý: Admin nên can thiệp kiểm tra lại file thiết kế hoặc đổi Designer để tránh trễ hạn.</i>"
        ),
    },
    {
        "template_key": "admin_deadline_overdue",
        "audience": "admin",
        "body": (
            "⏰ <b>DESIGNER QUÁ HẠN!</b>\n"
            "👤 <b>Designer:</b> {{designer_name}}\n"
            "📦 <b>Số đơn quá hạn:</b> {{order_count}}\n"
            "👉 Admin kiểm tra và xử lý các đơn trên Tacahu."
        ),
    },
    {
        "template_key": "admin_system_alert",
        "audience": "admin",
        "body": (
            "🔥 <b>CẢNH BÁO HỆ THỐNG: {{title}}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏢 <b>Platform:</b> {{platform_name}}\n"
            "❌ <b>Chi tiết:</b> {{message}}\n"
            "⏰ <b>Thời gian:</b> {{time}}"
        ),
    },
]


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_group_chat_id", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("telegram_group_title", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("telegram_group_type", sa.String(length=32), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "telegram_group_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("telegram_group_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("users", sa.Column("telegram_group_last_error", sa.String(length=1024), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "telegram_delivery_mode",
            sa.String(length=16),
            server_default=sa.text("'private'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_telegram_delivery_mode",
        "users",
        "telegram_delivery_mode IN ('private', 'group')",
    )
    op.create_index(
        "uq_users_telegram_group_chat_id",
        "users",
        ["telegram_group_chat_id"],
        unique=True,
        postgresql_where=sa.text("telegram_group_chat_id IS NOT NULL"),
    )

    op.create_table(
        "telegram_message_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key"),
    )
    op.create_check_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        "audience IN ('designer', 'admin')",
    )

    op.create_table(
        "telegram_configuration_audits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("target_user_id", sa.UUID(), nullable=True),
        sa.Column("template_key", sa.String(length=64), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_configuration_audits_target_user_id",
        "telegram_configuration_audits",
        ["target_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_configuration_audits_created_at",
        "telegram_configuration_audits",
        ["created_at"],
        unique=False,
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
            for item in DEFAULT_TEMPLATES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_configuration_audits_created_at", table_name="telegram_configuration_audits")
    op.drop_index("ix_telegram_configuration_audits_target_user_id", table_name="telegram_configuration_audits")
    op.drop_table("telegram_configuration_audits")
    op.drop_constraint(
        "ck_telegram_message_templates_audience",
        "telegram_message_templates",
        type_="check",
    )
    op.drop_table("telegram_message_templates")
    op.drop_index("uq_users_telegram_group_chat_id", table_name="users")
    op.drop_constraint("ck_users_telegram_delivery_mode", "users", type_="check")
    op.drop_column("users", "telegram_delivery_mode")
    op.drop_column("users", "telegram_group_last_error")
    op.drop_column("users", "telegram_group_verified_at")
    op.drop_column("users", "telegram_group_verified")
    op.drop_column("users", "telegram_group_type")
    op.drop_column("users", "telegram_group_title")
    op.drop_column("users", "telegram_group_chat_id")
