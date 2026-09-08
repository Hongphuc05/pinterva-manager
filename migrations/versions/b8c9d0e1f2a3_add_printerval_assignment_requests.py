"""add per-order Printerval assignment requests

Revision ID: b8c9d0e1f2a3
Revises: 5170b6101e92
Create Date: 2026-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "5170b6101e92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("printerval_designer", sa.String(length=255), nullable=True))
    op.add_column(
        "orders", sa.Column("printerval_designer_synced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "printerval_assignment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("internal_designer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("designer_option", sa.String(length=255), nullable=False),
        sa.Column("target_status", sa.String(length=32), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("observed_designer", sa.String(length=255), nullable=True),
        sa.Column("observed_status", sa.String(length=32), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["internal_designer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_printerval_assignment_requests_order_created",
        "printerval_assignment_requests",
        ["order_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_printerval_assignment_requests_order_created", "printerval_assignment_requests")
    op.drop_table("printerval_assignment_requests")
    op.drop_column("orders", "printerval_designer_synced_at")
    op.drop_column("orders", "printerval_designer")
