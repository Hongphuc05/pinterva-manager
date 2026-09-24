"""prevent duplicate active local comparison jobs per platform"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_active_compare_job_platform"
down_revision: str | None = "0005_local_compare_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"
INDEX = "uq_support_compare_jobs_active_platform"


def upgrade() -> None:
    op.create_index(
        INDEX,
        "comparison_jobs",
        ["platform_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="comparison_jobs", schema=SCHEMA)
