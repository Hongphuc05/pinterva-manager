"""custom configuration of historical (pool) jobs, shown in the duplicate Telegram message"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_historical_custom_config"
down_revision: str | None = "0007_item_review_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.add_column(
        "historical_jobs",
        sa.Column("custom_config", postgresql.JSONB(), nullable=True),
        schema=SCHEMA,
    )
    # Set once the backfill (or a live promotion) has looked the job up, even when it has no
    # configuration, so "not fetched yet" and "fetched, none" stay distinguishable.
    op.add_column(
        "historical_jobs",
        sa.Column("custom_config_synced_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("historical_jobs", "custom_config_synced_at", schema=SCHEMA)
    op.drop_column("historical_jobs", "custom_config", schema=SCHEMA)
