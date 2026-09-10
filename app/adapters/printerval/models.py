from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.adapters.base_models import AdapterResult


class OrderSummary(BaseModel):
    external_order_id: str
    product_name: str
    thumbnail_url: str | None = None
    designer: str | None = None
    status: str
    sku: str | None = None
    product_category: str | None = None
    product_skus: list[dict] | None = None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    product_image_urls: list[str] | None = None


class DiscoverResult(AdapterResult):
    orders: list[OrderSummary] = []
    cursor: str | None = None


class DesignerOptionsResult(AdapterResult):
    options: list[str] = []


class ProductVariant(BaseModel):
    name: str
    value: str


class CustomConfigEntry(BaseModel):
    key: str
    value: str


class CustomConfig(BaseModel):
    original: list[CustomConfigEntry] = []
    translated_vn: list[CustomConfigEntry] = []


class ProductSku(BaseModel):
    """One sellable SKU inside a Printerval design job.

    A design job can contain more than one SKU (for example XL and 2XL). Keeping
    them as a list prevents the first item from overwriting the rest of the order.
    """

    sku: str | None = None
    image_url: str | None = None
    category: str | None = None
    variants: list[ProductVariant] = []
    custom_config: CustomConfig | None = None


class OrderDetailResult(AdapterResult):
    external_order_id: str | None = None
    designer: str | None = None
    status: str | None = None
    note_outsource: str = ""
    order_note: str = ""
    created_at: datetime | None = None
    order_created_at: datetime | None = None
    deadline_at: datetime | None = None
    has_uploaded_design: bool = False
    product_name: str | None = None
    thumbnail_url: str | None = None
    sku: str | None = None
    product_category: str | None = None
    product_variants: list[ProductVariant] = []
    product_skus: list[ProductSku] = []
    multiple_design: bool = False
    double_sided: bool = False
    priority_label: str | None = None
    custom_config: CustomConfig | None = None
    design_tool_url: str | None = None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    product_image_urls: list[str] | None = None


class WriteResult(AdapterResult):
    external_order_id: str
    observed_state: dict = {}


class AssetResult(AdapterResult):
    external_order_id: str
    local_path: str | None = None
    checksum: str | None = None
