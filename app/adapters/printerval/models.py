from __future__ import annotations

from pydantic import BaseModel

from app.adapters.errors import ErrorClass


class AdapterResult(BaseModel):
    success: bool
    evidence: dict = {}
    error_class: ErrorClass | None = None
    retryable: bool = False


class OrderSummary(BaseModel):
    external_order_id: str
    product_name: str
    thumbnail_url: str | None = None
    designer: str | None = None
    status: str


class DiscoverResult(AdapterResult):
    orders: list[OrderSummary] = []
    cursor: str | None = None


class OrderDetailResult(AdapterResult):
    external_order_id: str | None = None
    designer: str | None = None
    status: str | None = None
    note_outsource: str = ""
    order_note: str = ""
    created_at: str | None = None
    order_created_at: str | None = None
    deadline_at: str | None = None
    has_uploaded_design: bool = False


class WriteResult(AdapterResult):
    external_order_id: str
    observed_state: dict = {}


class AssetResult(AdapterResult):
    external_order_id: str
    local_path: str | None = None
    checksum: str | None = None
