"""allow the recurring Support Waiting/Doing comparison source"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_support_unchecked_source"
down_revision: str | None = "0003_comparison_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"
CONSTRAINT = "ck_support_compare_comparison_source_kind"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "comparison_runs", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "comparison_runs",
        "source_kind IN ('review', 'waiting', 'support_unchecked', 'manual')",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "comparison_runs", schema=SCHEMA, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "comparison_runs",
        "source_kind IN ('review', 'waiting', 'manual')",
        schema=SCHEMA,
    )
