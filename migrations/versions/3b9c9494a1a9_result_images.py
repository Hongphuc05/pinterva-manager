"""result_images: mockup images Designers attach to a submission, pushed to Printerval's Design column

Revision ID: 3b9c9494a1a9
Revises: b3e4f5a6c7d8
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3b9c9494a1a9"
down_revision = "b3e4f5a6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "result_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("printerval_image_url", sa.String(1024), nullable=True),
        sa.Column("printerval_design_id", sa.Integer(), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_result_images_order_id", "result_images", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_result_images_order_id", table_name="result_images")
    op.drop_table("result_images")
