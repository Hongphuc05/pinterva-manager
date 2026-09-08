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
    has_template: bool = False
    template_jobs: list[dict] | None = None
    sku: str | None = None
    product_category: str | None = None


class DiscoverResult(AdapterResult):
    orders: list[OrderSummary] = []
    cursor: str | None = None


class ProductVariant(BaseModel):
    name: str
    value: str


class CustomConfigEntry(BaseModel):
    key: str
    value: str


class CustomConfig(BaseModel):
    original: list[CustomConfigEntry] = []
    translated_vn: list[CustomConfigEntry] = []


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
    has_template: bool = False
    multiple_design: bool = False
    double_sided: bool = False
    priority_label: str | None = None
    custom_config: CustomConfig | None = None
    template_jobs: list[dict] | None = None
    design_tool_url: str | None = None


class WriteResult(AdapterResult):
    external_order_id: str
    observed_state: dict = {}


class AssetResult(AdapterResult):
    external_order_id: str
    local_path: str | None = None
    checksum: str | None = None
