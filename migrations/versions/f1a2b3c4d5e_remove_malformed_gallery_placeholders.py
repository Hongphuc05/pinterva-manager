"""remove malformed gallery lazy-loading placeholders

Revision ID: f1a2b3c4d5e
Revises: ea2b3c4d5e6f
Create Date: 2026-09-18
"""

from alembic import op


revision = "f1a2b3c4d5e"
down_revision = "ea2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An older browser extractor turned data:/blob: lazy-load placeholders into
    # invalid HTTP URLs (for example https://printerval.comdata:image/...).
    # Remove only that impossible pattern while preserving every real gallery image.
    op.execute(
        """
        UPDATE orders AS o
        SET product_image_urls = (
            SELECT COALESCE(
                jsonb_agg(to_jsonb(image_url) ORDER BY ordinal),
                '[]'::jsonb
            )
            FROM jsonb_array_elements_text(o.product_image_urls)
                WITH ORDINALITY AS item(image_url, ordinal)
            WHERE image_url !~* '^https?://(www\\.)?printerval\\.com(data:|blob:|javascript:|about:)'
        )
        WHERE o.product_image_urls IS NOT NULL
          AND jsonb_typeof(o.product_image_urls) = 'array'
          AND EXISTS (
              SELECT 1
              FROM jsonb_array_elements_text(o.product_image_urls) AS existing(image_url)
              WHERE image_url ~* '^https?://(www\\.)?printerval\\.com(data:|blob:|javascript:|about:)'
          )
        """
    )


def downgrade() -> None:
    # Removed URLs were non-resolvable placeholders and cannot be recovered.
    pass
