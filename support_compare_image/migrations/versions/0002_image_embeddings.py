"""add image embeddings for the duplicate model (dup-compare)

Model contract (must match dup-compare/backend/embedding.py):
- model_version = HuggingFace model name, e.g. "facebook/dinov2-base"
- embedding = float32 little-endian bytes, L2-normalized, mean-pooled patch tokens
  (768 dims for dinov2-base); metric = cosine (= dot product)
- phash = 256-bit perceptual hash hex (imagehash, hash_size=16)
- color_l/a/b = mean CIE LAB of the image resized to 128x128

Stored as bytea, not pgvector: similarity search runs in RAM on the compare
machine, so no Postgres extension is needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_image_embeddings"
down_revision: str | None = "0001_support_compare_image"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "support_compare_image"


def upgrade() -> None:
    op.create_table(
        "image_embeddings",
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("embedding_dim", sa.Integer(), nullable=False),
        sa.Column("phash", sa.String(length=128), nullable=False),
        sa.Column("color_l", sa.Float(), nullable=False),
        sa.Column("color_a", sa.Float(), nullable=False),
        sa.Column("color_b", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["asset_id"], [f"{SCHEMA}.image_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id", "model_version", name="pk_support_compare_image_embeddings"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("image_embeddings", schema=SCHEMA)
