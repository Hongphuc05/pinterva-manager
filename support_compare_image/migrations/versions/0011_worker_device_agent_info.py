"""what a Support agent reports about itself (machine kind, pool/job progress) for the other accounts"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_worker_device_agent_info"
down_revision: str | None = "0010_review_access_job_orders"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.add_column(
        "worker_devices", sa.Column("agent_info", postgresql.JSONB(), nullable=True), schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_column("worker_devices", "agent_info", schema=SCHEMA)
