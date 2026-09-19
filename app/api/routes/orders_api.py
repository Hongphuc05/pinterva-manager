import base64
import math
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    ApprovalDecision,
    ApprovalRequest,
    Assignment,
    ExternalObservation,
    FinanceNote,
    Order,
    OrderAsset,
    Platform,
    PrintervalAssignmentRequest,
    ResultVersion,
    User,
    WorkflowEvent,
)
from app.adapters.printerval import login_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.api.deps import (
    DEFAULT_PLATFORM_ID,
    get_current_platform_id,
    get_current_user,
    get_db,
    require_any_role,
    require_role,
)
from app.application.assignment_commands import (
    AssignmentCommandError,
    revoke_assignment_command,
)
from app.application.crawl import DiscoverFailedError, refresh_order_detail, scan_orders_fast
from app.application.order_queries import (
    FIX_STATES,
    get_order_detail_for_user,
    get_order_history,
    is_unreleased_fix,
    list_orders_for_user,
)
from app.application.order_transitions import apply_transition
from app.application.printerval_assignment_requests import (
    PRINTERVAL_STATUSES,
    PrintervalAssignmentValidationError,
    create_request,
)
from app.application.sanitization import (
    decode_proxy_url,
    sanitize_order_detail_for_designer,
    sanitize_order_summary_for_designer,
    sanitize_workflow_event_for_designer,
)
from app.config import get_settings
from app.domain.access import (
    ROLE_ADMIN,
    ROLE_DESIGNER,
    ROLE_DESIGNER_TRELLO,
    ROLE_SUPPORT,
    WORK_DOMAIN_DUPLICATE,
    WORK_DOMAIN_STANDARD,
)
from app.domain.models import OrderState

router = APIRouter()


class OrderSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    work_domain: str = "standard"
    batch_id: uuid.UUID | None
    product_name: str | None = None
    sku: str | None = None
    thumbnail_url: str | None = None
    assigned_designer_name: str | None = None
    assigned_designer_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    product_skus: list[dict] | None = None
    order_created_at_ext: datetime | None = None
    deadline_at_ext: datetime | None = None
    created_at: datetime
    # Read-only mirror of Printerval's own site status — never written back to the
    # site from here (see app/application/status_sync.py).
    printerval_status: str | None = None
    platform_status: str | None = None
    printerval_status_synced_at: datetime | None = None
    platform_status_synced_at: datetime | None = None
    status_changed_at: datetime | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    fix_rejected_by_admin: bool = False
    fix_return_count: int = 0
    designer_note: str = ""
    template_missing: bool = False
    duplicate_check_status: str = "uncheck"
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    product_image_urls: list[str] | None = None
    printerval_designer: str | None = None
    platform_designer: str | None = None
    printerval_assignment_lifecycle: str | None = None
    platform_assignment_lifecycle: str | None = None
    printerval_assignment_error: str | None = None
    platform_assignment_error: str | None = None
    is_paid: bool = False
    paid_at: datetime | None = None
    review_submitted_at: datetime | None = None


class OrdersListResponse(BaseModel):
    orders: list[Any]


CRAWLED_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "crawled_assets"


@router.get("/assets/proxy")
def api_asset_proxy(u: str = Query(...)):
    raw_url = decode_proxy_url(u)
    if not raw_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired asset token")
    try:
        import httpx

        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
        ) as client:
            resp = client.get(raw_url)
            if resp.status_code != 200:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Asset not found")
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to load asset") from exc


def _is_allowed_gallery_url(url: str) -> bool:
    from app.application.gallery_helper import is_allowed_gallery_url

    return is_allowed_gallery_url(url)


class GalleryImportItem(BaseModel):
    external_order_id: str
    image_urls: list[str]
    product_url: str | None = None


class SingleGalleryImportResponse(BaseModel):
    ok: bool
    order_id: uuid.UUID
    external_order_id: str
    image_count: int


class BatchGalleryImportRequest(BaseModel):
    platform_id: uuid.UUID | None = None
    items: list[GalleryImportItem]


class BatchGalleryImportResponse(BaseModel):
    ok: bool
    synced_orders_count: int
    total_images_count: int
    message: str


@router.post("/integrations/printerval-gallery", response_model=SingleGalleryImportResponse)
@router.post("/integrations/platform-gallery", response_model=SingleGalleryImportResponse)
def import_single_printerval_gallery(
    payload: GalleryImportItem,
    platform_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Receive and update product gallery for a single order from Chrome extension."""
    from app.application.gallery_helper import deduplicate_gallery_urls

    raw_id = payload.external_order_id.strip()
    if not raw_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Thiếu mã đơn")

    m = re.search(r"([A-Za-z0-9_-]+)", raw_id)
    external_order_id = m.group(1).upper() if m else raw_id.upper()

    raw_allowed = [u.strip() for u in payload.image_urls if _is_allowed_gallery_url(u.strip())]
    image_urls = deduplicate_gallery_urls(raw_allowed)
    if not image_urls:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Không có ảnh hợp lệ để đồng bộ")

    from sqlalchemy import func
    query = db.query(Order).filter(func.upper(Order.external_order_id) == external_order_id)
    if platform_id:
        query = query.filter(Order.platform_id == platform_id)
    order = query.first()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Không tìm thấy đơn {external_order_id}")

    order.product_image_urls = image_urls
    db.commit()
    return SingleGalleryImportResponse(
        ok=True,
        order_id=order.id,
        external_order_id=order.external_order_id,
        image_count=len(image_urls),
    )


@router.post("/integrations/printerval-gallery/batch", response_model=BatchGalleryImportResponse)
@router.post("/integrations/platform-gallery/batch", response_model=BatchGalleryImportResponse)
def import_batch_printerval_gallery(
    payload: BatchGalleryImportRequest,
    db: Session = Depends(get_db),
):
    """Receive and update product galleries for multiple orders in bulk from Chrome extension."""
    from app.application.gallery_helper import deduplicate_gallery_urls

    if not payload.items:
        return BatchGalleryImportResponse(
            ok=True,
            synced_orders_count=0,
            total_images_count=0,
            message="Danh sách đơn trống, không có gì để đồng bộ.",
        )

    # Collect valid mapping of external_order_id -> image_urls
    clean_map: dict[str, list[str]] = {}
    for item in payload.items:
        raw_id = item.external_order_id.strip()
        if not raw_id:
            continue
        m = re.search(r"([A-Za-z0-9_-]+)", raw_id)
        ext_id = m.group(1).upper() if m else raw_id.upper()
        raw_allowed = [u.strip() for u in item.image_urls if _is_allowed_gallery_url(u.strip())]
        valid_urls = deduplicate_gallery_urls(raw_allowed)
        if valid_urls:
            clean_map[ext_id] = valid_urls

    if not clean_map:
        return BatchGalleryImportResponse(
            ok=True,
            synced_orders_count=0,
            total_images_count=0,
            message="Không tìm thấy ảnh hợp lệ trong payload.",
        )

    from sqlalchemy import func
    query = db.query(Order).filter(func.upper(Order.external_order_id).in_(list(clean_map.keys())))
    if payload.platform_id:
        query = query.filter(Order.platform_id == payload.platform_id)
    orders = query.all()

    synced_count = 0
    total_imgs = 0
    for order in orders:
        key = (order.external_order_id or "").strip().upper()
        imgs = clean_map.get(key)
        if imgs:
            order.product_image_urls = imgs
            synced_count += 1
            total_imgs += len(imgs)

    db.commit()
    return BatchGalleryImportResponse(
        ok=True,
        synced_orders_count=synced_count,
        total_images_count=total_imgs,
        message=f"Đã đồng bộ thành công {total_imgs} ảnh cho {synced_count} đơn hàng!",
    )


@router.get("/integrations/extension/download")
def download_extension_zip():
    """Package the CopyImage Chrome extension directory into a zip archive and stream it."""
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    # Possible CopyImage directory locations
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "CopyImage",
        Path(__file__).resolve().parent.parent.parent / "CopyImage",
        Path.cwd() / "CopyImage",
        Path("/app/CopyImage"),
    ]
    copy_image_dir = next((p for p in candidates if p.exists() and p.is_dir()), None)
    if not copy_image_dir:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Không tìm thấy thư mục extension CopyImage trên máy chủ",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in sorted(copy_image_dir.rglob("*")):
            if file_path.is_file() and not file_path.name.startswith("."):
                arcname = file_path.relative_to(copy_image_dir)
                zip_file.write(file_path, arcname)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="tacahu-copyimage-extension.zip"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )



class PendingGalleryOrder(BaseModel):
    id: uuid.UUID
    external_order_id: str
    product_name: str | None = None
    thumbnail_url: str | None = None
    sales_url: str | None = None
    image_count: int = 0


class PendingGalleriesResponse(BaseModel):
    orders: list[PendingGalleryOrder]


@router.get("/orders/pending-galleries", response_model=PendingGalleriesResponse)
def api_get_pending_galleries(
    state: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=10000),
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """List orders for the active platform to inspect/sync product galleries."""
    query = db.query(Order).filter(Order.platform_id == platform_id)
    if state:
        st = state.strip().upper()
        if st in ("WAITING", "OPEN"):
            query = query.filter(Order.state.in_(["WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING", "OPEN"]))
        else:
            query = query.filter(Order.state == st)
    orders = (
        query
        .order_by(Order.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for order in orders:
        sales_url = None
        if order.product_skus and isinstance(order.product_skus, list):
            for sku_item in order.product_skus:
                if isinstance(sku_item, dict) and sku_item.get("sales_url"):
                    sales_url = sku_item["sales_url"]
                    break
        if not sales_url and order.external_order_url and "orders?id=" not in order.external_order_url:
            sales_url = order.external_order_url

        if not sales_url:
            sku_to_check = order.sku
            if not sku_to_check and order.product_skus and isinstance(order.product_skus, list):
                for sku_item in order.product_skus:
                    if isinstance(sku_item, dict) and sku_item.get("sku"):
                        sku_to_check = sku_item["sku"]
                        break
            if sku_to_check:
                match = re.search(r'[pP](\d+)', str(sku_to_check))
                if match:
                    pid = match.group(1)
                    title = (order.product_name or 'product').lower()
                    slug = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-')
                    # Detect German storefront words
                    is_de = any(w in title for w in ['mit ', 'für ', 'und ', 'geschenk', 'becher', 'tasse', 'kissen', 'mütze', 'größe', 'weiss', 'weiß', 'schwarz'])
                    if is_de:
                        sales_url = f"https://printerval.com/de/{slug}-p{pid}"
                    else:
                        sales_url = f"https://printerval.com/{slug}-p{pid}"

        img_urls = order.product_image_urls or []
        result.append(
            PendingGalleryOrder(
                id=order.id,
                external_order_id=order.external_order_id,
                product_name=order.product_name,
                thumbnail_url=order.thumbnail_url,
                sales_url=sales_url,
                image_count=len(img_urls),
            )
        )
    return PendingGalleriesResponse(orders=result)


class UpdateGalleryPayload(BaseModel):
    image_urls: list[str]
    product_url: str | None = None
    designer_note: str | None = None
    note_outsource: str | None = None


class UpdateGalleryResponse(BaseModel):
    ok: bool
    order_id: uuid.UUID
    image_count: int
    designer_note: str | None = None
    note_outsource: str | None = None


class UploadGalleryImageRequest(BaseModel):
    filename: str
    content_base64: str


class UploadGalleryImageResponse(BaseModel):
    ok: bool
    image_url: str


@router.post("/orders/{order_id}/upload-gallery-image", response_model=UploadGalleryImageResponse)
def api_upload_gallery_image(
    order_id: str,
    payload: UploadGalleryImageRequest,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Admin endpoint to upload a product gallery image from local device."""
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    filename = payload.filename or "image.png"
    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        ext = ".png"

    raw_data = payload.content_base64
    if "," in raw_data:
        raw_data = raw_data.split(",", 1)[1]

    try:
        content = base64.b64decode(raw_data)
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dữ liệu ảnh base64 không hợp lệ")

    if len(content) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File ảnh vượt quá dung lượng cho phép (25MB)")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    target_dir = CRAWLED_ASSETS_DIR / "galleries" / str(order.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / safe_name

    with open(target_path, "wb") as f:
        f.write(content)

    rel_url = f"/crawled_assets/galleries/{order.id}/{safe_name}"
    return UploadGalleryImageResponse(ok=True, image_url=rel_url)


@router.patch("/orders/{order_id}/gallery", response_model=UpdateGalleryResponse)
def api_update_order_gallery(
    order_id: str,
    payload: UpdateGalleryPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Admin-only update of an order's product gallery images and notes."""
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    from app.application.gallery_helper import deduplicate_gallery_urls

    raw_allowed = [u.strip() for u in payload.image_urls if u.strip() and _is_allowed_gallery_url(u.strip())]
    clean_images = deduplicate_gallery_urls(raw_allowed)

    order.product_image_urls = clean_images
    if payload.designer_note is not None:
        order.designer_note = payload.designer_note.strip()
    if payload.note_outsource is not None:
        order.note_outsource = payload.note_outsource.strip()

    db.add(WorkflowEvent(
        order_id=order.id,
        from_state=order.state,
        to_state=order.state,
        actor_id=user.id,
        evidence={
            "action": "UPDATE_GALLERY_IMAGES",
            "actor_role": "admin",
            "actor_name": user.full_name or user.username,
            "description": f"Admin cập nhật {len(clean_images)} ảnh chi tiết sản phẩm / ghi chú.",
            "image_count": len(clean_images),
        },
    ))
    db.commit()
    return UpdateGalleryResponse(
        ok=True,
        order_id=order.id,
        image_count=len(clean_images),
        designer_note=order.designer_note,
        note_outsource=order.note_outsource,
    )


@router.post("/orders/{order_id}/sync-gallery", response_model=UpdateGalleryResponse)
def api_trigger_order_gallery_sync(
    order_id: str,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Admin endpoint to scrape & sync product gallery directly on the server."""
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    # Determine sales_url
    sales_url = None
    if order.product_skus and isinstance(order.product_skus, list):
        for sku_item in order.product_skus:
            if isinstance(sku_item, dict) and sku_item.get("sales_url"):
                sales_url = sku_item["sales_url"]
                break
    if not sales_url and order.external_order_url and "orders?id=" not in order.external_order_url:
        sales_url = order.external_order_url
    if not sales_url:
        sku_to_check = order.sku
        if not sku_to_check and order.product_skus and isinstance(order.product_skus, list):
            for sku_item in order.product_skus:
                if isinstance(sku_item, dict) and sku_item.get("sku"):
                    sku_to_check = sku_item["sku"]
                    break
        if sku_to_check:
            match = re.search(r'[pP](\d+)', str(sku_to_check))
            if match:
                pid = match.group(1)
                title = (order.product_name or 'product').lower()
                slug = re.sub(r'[^a-zA-Z0-9]+', '-', title).strip('-')
                is_de = any(w in title for w in ['mit ', 'für ', 'und ', 'geschenk', 'becher', 'tasse', 'kissen', 'mütze', 'größe', 'weiss', 'weiß', 'schwarz'])
                if is_de:
                    sales_url = f"https://printerval.com/de/{slug}-p{pid}"
                else:
                    sales_url = f"https://printerval.com/{slug}-p{pid}"

    if not sales_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Không xác định được link sản phẩm")

    try:
        from playwright.sync_api import sync_playwright

        from app.adapters.printerval.gallery_scraper import PLAYWRIGHT_EXTRACT_GALLERY_SNIPPET

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.goto(sales_url, timeout=25000, wait_until='domcontentloaded')
            page.wait_for_timeout(2500)
            res = page.evaluate(PLAYWRIGHT_EXTRACT_GALLERY_SNIPPET, sales_url)
            browser.close()

            if res.get('success') and res.get('images'):
                clean_images = []
                for u in res['images']:
                    u = u.strip()
                    if u and _is_allowed_gallery_url(u) and u not in clean_images:
                        clean_images.append(u)
                if clean_images:
                    order.product_image_urls = clean_images
                    db.commit()
                    return UpdateGalleryResponse(ok=True, order_id=order.id, image_count=len(clean_images))
    except Exception:
        pass

    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Không bóc tách được ảnh sản phẩm từ trang")



class ResultVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    drive_url: str
    version_marker: int
    submitted_at: datetime | None = None
    qc_feedback: str | None = None


class OrderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    external_order_id: str
    state: str
    work_domain: str = "standard"
    batch_id: uuid.UUID | None
    product_name: str | None
    thumbnail_url: str | None
    sku: str | None
    product_category: str | None
    product_variants: list[dict] | None
    multiple_design: bool
    double_sided: bool
    priority_label: str | None
    deadline_at_ext: datetime | None
    order_created_at_ext: datetime | None = None
    created_at_ext: datetime | None = None
    note_outsource: str
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    fix_rejected_by_admin: bool = False
    fix_return_count: int = 0
    designer_note: str = ""
    template_missing: bool = False
    duplicate_check_status: str = "uncheck"
    custom_config: dict | None
    product_skus: list[dict] | None = None
    assigned_designer_name: str | None = None
    assignment_id: uuid.UUID | None = None
    sub_status: str | None = None
    result_versions: list[ResultVersionOut] = []
    design_tool_url: str | None
    sku_image_url: str | None = None
    external_order_url: str | None = None
    source_files: list[dict] | None = None
    source_download_all_url: str | None = None
    product_image_urls: list[str] | None = None
    printerval_designer: str | None = None
    platform_designer: str | None = None
    printerval_status: str | None = None
    platform_status: str | None = None
    status_changed_at: datetime | None = None
    created_at: datetime



class WorkflowEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str | None = None
    created_at: datetime
    from_state: str | None = None
    to_state: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str | None = None
    description: str | None = None
    designer_name: str | None = None
    evidence: dict | None = None


class OrderHistoryItemOut(BaseModel):
    id: str
    created_at: datetime
    order_id: str
    external_order_id: str
    product_name: str | None = None
    thumbnail_url: str | None = None
    from_state: str | None = None
    to_state: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    action: str | None = None
    description: str | None = None
    designer_name: str | None = None
    evidence: dict | None = None


class OrderHistoryListResponse(BaseModel):
    items: list[OrderHistoryItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class OrderDetailResponse(BaseModel):
    order: Any
    history: list[WorkflowEventOut | Any]


class RefreshResponse(BaseModel):
    flash: str
    summary: dict | None = None


class SyncStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    is_running: bool
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_result: dict | None = None
    last_error: str | None = None


class RefreshRequest(BaseModel):
    # Mirrors Printerval's own filter bar (Loại design job). Only "Tất cả 2D & 3D" is
    # confirmed safe on the fast HTTP API path (docs/phase0-field-map.md §4); any other
    # value routes this crawl through the slower, DOM-verified Playwright fallback
    # instead of guessing an unconfirmed HTTP query value for it (a real past incident:
    # a wrong filter string silently returned 0 orders instead of erroring).
    job_type: str = ALL_JOB_TYPES
    printerval_status: str = "Waiting"
    printerval_designer: str | None = None
    # Plain "YYYY-MM-DD" from the date picker (filters on created_at) — live-confirmed
    # 2026-09-08 against the real site's own find endpoint (date_from/date_to,
    # "YYYY-MM-DD HH:MM:SS"). Only applies on the fast HTTP path (job_type == default).
    date_from: str | None = None
    date_to: str | None = None


class PrintervalLoginStatus(BaseModel):
    session_open: bool


class OrderStatesResponse(BaseModel):
    states: list[str]


class PrintervalOptionsResponse(BaseModel):
    designers: list[str]
    statuses: list[str]
    synced_at: datetime | None = None


class PrintervalAssignmentPayload(BaseModel):
    # Optional: a quick Printerval-only edit (e.g. from the read-only status mirror
    # tab) doesn't need to also assign this order to an internal designer — only the
    # site-side Designer/Status actually change then. When given, the internal
    # Assignment/state are updated too, same as before.
    designer_id: str | None = None
    printerval_designer: str
    printerval_status: str = "Doing"


class PrintervalAssignmentResponse(BaseModel):
    request_id: uuid.UUID
    lifecycle: str


class BulkPrintervalAssignmentPayload(BaseModel):
    order_ids: list[str]
    designer_id: str | None = None
    printerval_designer: str | None = None
    printerval_status: str = "Doing"


class BulkPrintervalAssignmentResponse(BaseModel):
    request_ids: list[uuid.UUID]
    queued_count: int


@router.get("/order-states", response_model=OrderStatesResponse)
def api_order_states(user: User = Depends(get_current_user)):
    return OrderStatesResponse(states=[s.value for s in OrderState])


@router.get("/orders", response_model=OrdersListResponse)
def api_orders_list(
    status_filter: str | None = Query(default=None, alias="status"),
    batch_id: str | None = None,
    designer_id: str | None = None,
    work_domain: str | None = None,
    duplicate_check_status: str | None = None,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    orders = list_orders_for_user(
        db,
        user,
        status=status_filter,
        batch_id=batch_id,
        designer_id=designer_id,
        platform_id=platform_id,
        work_domain=work_domain,
        duplicate_check_status=duplicate_check_status,
    )
    order_ids = [o.id for o in orders]
    assignments = (
        db.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(Assignment.order_id.in_(order_ids), Assignment.status == "approved")
        .all()
        if order_ids
        else []
    )
    designer_map = {a.order_id: u.full_name or u.username for a, u in assignments}
    designer_id_map = {a.order_id: u.id for a, u in assignments}
    assignment_id_map = {a.order_id: a.id for a, _ in assignments}
    requests = (
        db.query(PrintervalAssignmentRequest)
        .filter(PrintervalAssignmentRequest.order_id.in_(order_ids))
        .order_by(PrintervalAssignmentRequest.created_at.desc())
        .all()
        if order_ids
        else []
    )
    request_map = {}
    for request in requests:
        request_map.setdefault(request.order_id, request)

    is_admin = user.role == ROLE_ADMIN
    out_list = []
    for o in orders:
        item = OrderSummaryOut.model_validate(o)
        item.assigned_designer_name = designer_map.get(o.id)
        if not item.assigned_designer_name and (
            (user.printerval_designer_option and o.printerval_designer == user.printerval_designer_option)
            or (user.full_name and o.printerval_designer == user.full_name)
        ):
            item.assigned_designer_name = user.full_name or user.username
        item.assigned_designer_id = designer_id_map.get(o.id)
        item.assignment_id = assignment_id_map.get(o.id)
        latest_request = request_map.get(o.id)
        item.printerval_assignment_lifecycle = latest_request.lifecycle if latest_request else None
        if latest_request and latest_request.lifecycle in ("failed", "unknown_outcome"):
            item.printerval_assignment_error = (
                f"{latest_request.error_class}: {latest_request.error_message}"
                if latest_request.error_message
                else latest_request.error_class
            )
        if not is_admin:
            item = sanitize_order_summary_for_designer(item)
        out_list.append(item)

    return OrdersListResponse(orders=out_list)


# Declared before /orders/{order_id} — a literal path segment after a path-param
# route of the same method would otherwise never be reached (FastAPI/Starlette
# matches routes in declaration order; "sync-status" would be swallowed as order_id).
@router.get("/orders/sync-status", response_model=SyncStatusResponse)
def api_orders_sync_status(
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    from app.adapters.db.models import PlatformSyncState

    state = db.get(PlatformSyncState, platform_id)
    if state is None:
        return SyncStatusResponse(is_running=False)

    # Automatically recover if is_running was stuck for > 3 minutes (180s)
    if state.is_running and state.last_started_at:
        now = datetime.now(UTC)
        started_at = state.last_started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if (now - started_at).total_seconds() > 180:
            state.is_running = False
            state.last_finished_at = now
            state.last_error = "Đã tự động khôi phục do tác vụ đồng bộ quá thời gian (timeout)."
            db.commit()

    return SyncStatusResponse.model_validate(state)


@router.post("/orders/sync-status/run", response_model=SyncStatusResponse)
def api_orders_sync_status_run(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Manual "refresh now" — marks platform as running and dispatches background sync non-blockingly."""
    from app.adapters.db.models import PlatformSyncState

    state = db.get(PlatformSyncState, platform_id)
    if state is None:
        state = PlatformSyncState(platform_id=platform_id)
        db.add(state)
    state.is_running = True
    state.last_started_at = datetime.now(UTC)
    state.last_error = None
    db.commit()

    try:
        from app.workers.status_sync_tasks import sync_order_statuses

        sync_order_statuses.delay()
    except Exception:
        # Fallback if Celery broker is not running: execute in daemon background thread
        import threading

        from app.adapters.db.session import SessionLocal
        from app.application.status_sync import sync_all_platforms

        def bg_run():
            s = SessionLocal()
            try:
                sync_all_platforms(s)
            except Exception:
                pass
            finally:
                s.close()

        threading.Thread(target=bg_run, daemon=True).start()

    return SyncStatusResponse.model_validate(state)


@router.post("/orders/sync-status/reset", response_model=SyncStatusResponse)
def api_orders_sync_status_reset(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Force reset the is_running lock if stuck."""
    from app.adapters.db.models import PlatformSyncState

    state = db.get(PlatformSyncState, platform_id)
    if state:
        state.is_running = False
        state.last_finished_at = datetime.now(UTC)
        db.commit()
        return SyncStatusResponse.model_validate(state)
    return SyncStatusResponse(is_running=False)


class RefreshOrderDetailResponse(BaseModel):
    ok: bool
    message: str


@router.post("/orders/{order_id}/refresh-detail", response_model=RefreshOrderDetailResponse)
def api_refresh_order_detail(
    order_id: str,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """"Cập nhật toàn bộ" for one order from the "Trạng Thái Đơn" tab — re-fetches
    everything the crawl's one-time import would have captured (SKU details, source
    files, images, deadline, product info...), for an order that's already past
    that point. import_claimed_orders only ever runs once per order (gated on state);
    this exists because product and source details can change after the first import.
    Synchronous, same shape as /orders/refresh — a single order's detail fetch is
    normally sub-second on the fast HTTP path."""
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_password or platform.session_cookie) or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform chưa có Session Cookie hoặc mật khẩu, hoặc chưa có Team Outsource Printerval.",
        )
    settings = get_settings()
    with PrintervalApiClient(
        base_url=settings.printerval_api_base_url,
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    ) as api_client:
        adapter = PrintervalApiAdapter(api_client=api_client, download_images=True)
        result = refresh_order_detail(db, adapter, order)
    if not result["success"]:
        return RefreshOrderDetailResponse(
            ok=False,
            message=f"Không cập nhật được đơn {order.external_order_id} (lỗi ở bước {result['stage']}) — xem dead_letters.",
        )
    return RefreshOrderDetailResponse(ok=True, message=f"Đã cập nhật toàn bộ thông tin đơn {order.external_order_id}.")


@router.get("/orders/{order_id}/printerval-options", response_model=PrintervalOptionsResponse)
@router.get("/orders/{order_id}/platform-options", response_model=PrintervalOptionsResponse)
def api_printerval_options(
    order_id: str,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    platform = db.get(Platform, platform_id)
    if platform is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    return PrintervalOptionsResponse(
        designers=platform.printerval_designer_options or [],
        statuses=platform.printerval_status_options or list(PRINTERVAL_STATUSES),
        synced_at=platform.printerval_options_synced_at,
    )


@router.post("/platforms/printerval-options/refresh", response_model=PrintervalOptionsResponse)
@router.post("/platforms/platform-options/refresh", response_model=PrintervalOptionsResponse)
def api_refresh_printerval_options(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_password or platform.session_cookie) or not platform.team_outsource:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Platform needs a Printerval session cookie or password and team scope",
        )
    settings = get_settings()
    try:
        with PrintervalApiClient(
            base_url=settings.printerval_api_base_url,
            username=platform.account_username,
            password=platform.account_password,
            team_outsource=platform.team_outsource,
            session_cookie=platform.session_cookie,
        ) as client:
            designers = client.list_designer_options()
    except (PrintervalApiConfigurationError, PrintervalApiError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not load Printerval Designer options",
        ) from exc
    platform.printerval_designer_options = designers
    platform.printerval_status_options = list(PRINTERVAL_STATUSES)
    platform.printerval_options_synced_at = datetime.now(UTC)
    db.commit()
    return PrintervalOptionsResponse(
        designers=designers,
        statuses=platform.printerval_status_options,
        synced_at=platform.printerval_options_synced_at,
    )


@router.post(
    "/orders/{order_id}/printerval-assignment",
    response_model=PrintervalAssignmentResponse,
)
@router.post(
    "/orders/{order_id}/platform-assignment",
    response_model=PrintervalAssignmentResponse,
)
def api_printerval_assignment(
    order_id: str,
    payload: PrintervalAssignmentPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None or order.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found for active platform")
    designer: User | None = None
    if payload.designer_id:
        try:
            designer = db.get(User, uuid.UUID(payload.designer_id))
        except ValueError:
            designer = None
        if designer is None or not designer.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found")
    if not payload.printerval_designer.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Printerval Designer is required")
    if payload.printerval_status not in PRINTERVAL_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Printerval status")
    if designer is not None:
        assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
        if assignment is None:
            assignment = Assignment(order_id=order.id, designer_id=designer.id, status="approved")
            db.add(assignment)
        else:
            assignment.designer_id = designer.id
            assignment.status = "approved"
        order.state = OrderState.WAITING.value
    try:
        request = create_request(
            db,
            order=order,
            # A pure Printerval-only edit (no internal designer chosen) still needs an
            # internal_designer_id for the audit trail (NOT NULL) — the acting admin
            # is the correct "who did this", not a guessed/forced designer pick.
            internal_designer=designer or user,
            platform_id=platform_id,
            designer_option=payload.printerval_designer,
            target_status=payload.printerval_status,
        )
    except PrintervalAssignmentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

    sync_printerval_assignment_request.delay(str(request.id))
    return PrintervalAssignmentResponse(request_id=request.id, lifecycle=request.lifecycle)


@router.post(
    "/orders/bulk-printerval-assignment",
    response_model=BulkPrintervalAssignmentResponse,
)
@router.post(
    "/orders/bulk-platform-assignment",
    response_model=BulkPrintervalAssignmentResponse,
)
def api_bulk_printerval_assignment(
    payload: BulkPrintervalAssignmentPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    if not payload.order_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng không được để trống")
    designer: User | None = None
    if payload.designer_id:
        try:
            designer_id = uuid.UUID(payload.designer_id)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID") from exc
        designer = db.get(User, designer_id)
        if designer is None or not designer.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found")

    has_printerval_designer = bool(payload.printerval_designer and payload.printerval_designer.strip())
    if payload.printerval_status not in PRINTERVAL_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Printerval status")
    try:
        order_ids = [uuid.UUID(order_id) for order_id in payload.order_ids]
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order ID") from exc
    if len(set(order_ids)) != len(order_ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng bị trùng")
    orders = db.query(Order).filter(Order.id.in_(order_ids)).all()
    if len(orders) != len(order_ids) or any(order.platform_id != platform_id for order in orders):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Mỗi đơn phải thuộc platform đang chọn",
        )

    # If Printerval Designer is provided, use the full request lifecycle
    if has_printerval_designer:
        requests: list[PrintervalAssignmentRequest] = []
        for order in orders:
            if designer is not None:
                assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
                if assignment is None:
                    db.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
                else:
                    assignment.designer_id = designer.id
                    assignment.status = "approved"
                order.state = OrderState.WAITING.value
            try:
                requests.append(
                    create_request(
                        db,
                        order=order,
                        internal_designer=designer or user,
                        platform_id=platform_id,
                        designer_option=payload.printerval_designer.strip(),
                        target_status=payload.printerval_status,
                    )
                )
            except PrintervalAssignmentValidationError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        from app.workers.assignment_sync_tasks import sync_printerval_assignment_request

        for request in requests:
            sync_printerval_assignment_request.delay(str(request.id))
        return BulkPrintervalAssignmentResponse(
            request_ids=[request.id for request in requests],
            queued_count=len(requests),
        )

    # Status-only update (or with optional internal designer change)
    from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task

    status_state_map = {
        "Doing": OrderState.IN_PROGRESS,
        "Review": OrderState.QC_PENDING,
        "Fix": OrderState.REVISION,
        "Done": OrderState.DONE,
        "Waiting": OrderState.WAITING,
        "Skipped": OrderState.DONE,
    }
    mapped_state = status_state_map.get(payload.printerval_status)

    for order in orders:
        if designer is not None:
            assignment = db.query(Assignment).filter(Assignment.order_id == order.id).one_or_none()
            if assignment is None:
                db.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
            else:
                assignment.designer_id = designer.id
                assignment.status = "approved"
        if mapped_state:
            order.state = mapped_state.value
            order.status_changed_at = datetime.now(UTC)
        order.printerval_status = payload.printerval_status.lower()
        order.printerval_status_synced_at = datetime.now(UTC)

        # Trigger background task to push status to Printerval via direct HTTP API
        sync_order_review_to_printerval_task.delay(str(order.id), None, payload.printerval_status)

    db.commit()
    return BulkPrintervalAssignmentResponse(
        request_ids=[],
        queued_count=len(orders),
    )



STATE_LABEL_VI: dict[str, str] = {
    "OPEN": "Waiting",
    "WAITING": "Waiting",
    "OPEN_FOR_ALLOCATION": "Waiting",
    "DISCOVERED": "Waiting",
    "PENDING": "Waiting",
    "IN_PROGRESS": "Doing",
    "DOING": "Doing",
    "ASSIGNED": "Doing",
    "QC_PENDING": "Review",
    "REVIEW": "Review",
    "REVISION": "Fix",
    "FIX": "Fix",
    "REVISION_REQUESTED": "Fix",
    "DONE": "Done",
    "COMPLETED": "Done",
    "CLAIMED_IMPORTED": "Done",
    "CANCELLED": "Đã hủy",
    "EXCEPTION": "Lỗi",
}


def get_friendly_state_label(state: str | None) -> str:
    if not state:
        return "Mới"
    return STATE_LABEL_VI.get(state.upper(), state)


def format_event_description(
    from_state: str | None,
    to_state: str,
    action: str | None,
    actor_name: str | None,
    actor_role: str | None,
    designer_name: str | None,
    raw_desc: str | None = None,
) -> str:
    from_st = (from_state or "").upper()
    to_st = (to_state or "").upper()
    act = (action or "").upper()
    actor_display = f"{'Admin ' if actor_role == 'admin' else ('Designer ' if actor_role == 'designer' else '')}{actor_name}" if actor_name else ""

    # If raw_desc is already custom and good (not the default 'Chuyển trạng thái từ...')
    if raw_desc and not raw_desc.startswith("Chuyển trạng thái từ ") and "chuyển trạng thái từ " not in raw_desc.lower():
        return raw_desc

    # Assignment
    if act in ("ASSIGN", "REASSIGN") or (from_st in ("OPEN", "DISCOVERED", "OPEN_FOR_ALLOCATION") and to_st in ("WAITING", "IN_PROGRESS", "DOING")):
        target_des = designer_name or "Designer"
        if actor_display:
            return f"{actor_display} phân công đơn cho {target_des}"
        return f"Phân công đơn cho {target_des}"

    # Waiting -> Doing
    if (from_st in ("WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING", "OPEN", "") and to_st in ("IN_PROGRESS", "DOING")) or act == "START_DOING":
        if actor_display:
            return f"{actor_display} nhận đơn vào Doing"
        return "Nhận đơn vào Doing"

    # Doing -> Review (Initial submission)
    if (from_st in ("IN_PROGRESS", "DOING", "ASSIGNED") and to_st in ("QC_PENDING", "REVIEW")) or (act == "SUBMIT_REVIEW" and from_st not in ("REVISION", "FIX", "REVISION_REQUESTED")):
        if actor_display:
            return f"{actor_display} nộp bài sang Review"
        return "Designer nộp bài sang Review"

    # Fix -> Review (Resubmission after fix)
    if (from_st in ("REVISION", "FIX", "REVISION_REQUESTED") and to_st in ("QC_PENDING", "REVIEW")) or act == "RESUBMIT_FIX":
        if actor_display:
            return f"{actor_display} nộp lại bài sau khi fix"
        return "Designer nộp lại bài sau khi fix"

    # Review -> Fix (Admin requests fix)
    if (from_st in ("QC_PENDING", "REVIEW") and to_st in ("REVISION", "FIX", "REVISION_REQUESTED")) or act == "REQUEST_FIX":
        if actor_display:
            return f"{actor_display} yêu cầu sửa bài (Fix)"
        return "Admin yêu cầu sửa bài (Fix)"

    # Review -> Done (Admin approves)
    if (from_st in ("QC_PENDING", "REVIEW") and to_st in ("DONE", "COMPLETED")) or act == "APPROVE_DONE":
        if actor_display:
            return f"{actor_display} duyệt hoàn thành đơn hàng (Done)"
        return "Admin duyệt hoàn thành đơn hàng (Done)"

    # Review -> Doing (Revert to edit)
    if (from_st in ("QC_PENDING", "REVIEW") and to_st in ("IN_PROGRESS", "DOING")) or act == "REVERT_TO_DOING":
        if actor_display:
            return f"{actor_display} chuyển lại về Doing để chỉnh sửa"
        return "Chuyển lại về Doing để chỉnh sửa"

    # Move to Waiting
    if to_st in ("WAITING", "OPEN_FOR_ALLOCATION") or act == "SET_WAITING":
        if actor_display:
            return f"{actor_display} chuyển đơn về Waiting"
        return "Chuyển đơn về Waiting"

    # Flag missing template
    if act == "FLAG_MISSING_TEMPLATE":
        if actor_display:
            return f"{actor_display} báo đơn thiếu template"
        return "Designer báo đơn thiếu template"

    # Generic friendly fallback
    from_lbl = get_friendly_state_label(from_state)
    to_lbl = get_friendly_state_label(to_state)
    if actor_display:
        return f"{actor_display}: {from_lbl} → {to_lbl}"
    return f"{from_lbl} → {to_lbl}"


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
def api_order_detail(
    order_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    history = get_order_history(db, order_id)

    assignment = (
        db.query(Assignment, User)
        .join(User, User.id == Assignment.designer_id)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .first()
    )
    order_out = OrderDetailOut.model_validate(order)
    if not order_out.product_image_urls and order.thumbnail_url:
        order_out.product_image_urls = [order.thumbnail_url]
    if assignment:
        asgn_obj, des_user = assignment
        order_out.assigned_designer_name = des_user.full_name or des_user.username
        order_out.assignment_id = asgn_obj.id
        order_out.sub_status = asgn_obj.sub_status
        versions = (
            db.query(ResultVersion)
            .filter(ResultVersion.assignment_id == asgn_obj.id)
            .order_by(ResultVersion.version_marker.asc())
            .all()
        )
        order_out.result_versions = [
            ResultVersionOut.model_validate(v) for v in versions
        ]


    actor_ids = {e.actor_id for e in history if e.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    history_out = []
    for e in history:
        actor_info = actors_map.get(e.actor_id)
        actor_name = (e.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (e.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action = (e.evidence or {}).get("action")
        designer_name = (e.evidence or {}).get("designer_name")
        description = format_event_description(
            from_state=e.from_state,
            to_state=e.to_state,
            action=action,
            actor_name=actor_name,
            actor_role=actor_role,
            designer_name=designer_name,
            raw_desc=(e.evidence or {}).get("description"),
        )

        history_out.append(
            WorkflowEventOut(
                id=str(e.id),
                created_at=e.created_at,
                from_state=e.from_state,
                to_state=e.to_state,
                actor_id=str(e.actor_id) if e.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action,
                description=description,
                designer_name=designer_name,
                evidence=e.evidence,
            )
        )

    is_admin = user.role == ROLE_ADMIN
    if not is_admin:
        order_out = sanitize_order_detail_for_designer(order_out)
        history_out = [sanitize_workflow_event_for_designer(ev) for ev in history_out]

    return OrderDetailResponse(
        order=order_out,
        history=history_out,
    )


@router.post("/orders/refresh", response_model=RefreshResponse)
def api_orders_refresh(
    payload: RefreshRequest = RefreshRequest(),
    user: User = Depends(require_any_role(ROLE_ADMIN, ROLE_SUPPORT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        settings = get_settings()
        platform = db.get(Platform, platform_id)
        if (
            platform is None
            or not platform.account_username
            or not (platform.account_password or platform.session_cookie)
            or not platform.team_outsource
        ):
            return RefreshResponse(
                flash="Platform chưa có Session Cookie hoặc mật khẩu, hoặc chưa có Team Outsource Printerval."
            )
        crawl_username = platform.account_username
        crawl_password = platform.account_password
        crawl_team_outsource = platform.team_outsource

        with PrintervalApiClient(
            base_url=settings.printerval_api_base_url,
            username=crawl_username,
            password=crawl_password,
            team_outsource=crawl_team_outsource,
            session_cookie=platform.session_cookie,
        ) as api_client:
            adapter = PrintervalApiAdapter(api_client=api_client, download_images=False)
            summary = scan_orders_fast(
                db,
                adapter,
                platform_id=platform_id,
                status=payload.printerval_status,
                designer=payload.printerval_designer,
                job_type=payload.job_type,
                date_from=f"{payload.date_from} 00:00:00" if payload.date_from else None,
                date_to=f"{payload.date_to} 23:59:59" if payload.date_to else None,
            )
        flash = (
            f"Đã quét nhanh qua API ({crawl_username}): {summary['scanned']} đơn khớp bộ lọc, "
            f"{summary['added']} đơn mới"
        )
        flash += "."
        return RefreshResponse(flash=flash, summary=summary)
    except DiscoverFailedError:
        db.rollback()
        flash = (
            f"Crawl thất bại khi tìm đơn mới cho tài khoản '{crawl_username}' — "
            "có thể tài khoản/mật khẩu chưa đúng hoặc team_outsource không khớp. "
            "Xem bảng dead_letters (source=crawl.discover_waiting_orders) để biết chi tiết lỗi."
        )
        return RefreshResponse(flash=flash)
    except Exception as exc:
        db.rollback()
        flash = f"Crawl thất bại ({crawl_username}): {str(exc)}"
        return RefreshResponse(flash=flash)


@router.get("/printerval-login/status", response_model=PrintervalLoginStatus)
@router.get("/platform-login/status", response_model=PrintervalLoginStatus)
def api_printerval_login_status(user: User = Depends(require_role("admin"))):
    return PrintervalLoginStatus(session_open=login_session.is_session_open())


@router.post("/printerval-login/start", response_model=PrintervalLoginStatus)
@router.post("/platform-login/start", response_model=PrintervalLoginStatus)
def api_printerval_login_start(user: User = Depends(require_role("admin"))):
    login_session.start_session()
    return PrintervalLoginStatus(session_open=True)


@router.post("/printerval-login/done", response_model=PrintervalLoginStatus)
@router.post("/platform-login/done", response_model=PrintervalLoginStatus)
def api_printerval_login_done(user: User = Depends(require_role("admin"))):
    login_session.close_session()
    return PrintervalLoginStatus(session_open=False)


class AssignOrderRequest(BaseModel):
    designer_id: str


def _trigger_printerval_assignment_sync(order: Order, designer: User) -> str:
    """Enqueues the background job that mirrors this assignment onto Printerval (set
    Designer + status=Doing) — never runs inline (Playwright is slow), never touches
    our own state machine (claude.md §5 — the designer's own "Bắt đầu" action still
    owns ASSIGNED -> IN_PROGRESS). Returns a short status message for the response,
    it does not wait for the sync itself to finish."""
    if not designer.printerval_designer_option:
        return (
            f"Đã phân công nội bộ cho {designer.full_name or designer.username}. "
            "Designer này CHƯA có tên đăng ký trên Printerval (xem Quản Lý Tài Khoản) "
            "nên KHÔNG đồng bộ sang Printerval — chỉ lưu nội bộ."
        )
    from app.workers.assignment_sync_tasks import sync_assignment_to_printerval_task

    sync_assignment_to_printerval_task.delay(str(order.id), str(designer.id))
    return "Đã phân công nội bộ, đang đồng bộ sang Printerval trong nền (Doing + đổi Designer)."


@router.post("/orders/{order_id}/assign")
def api_assign_order(
    order_id: str,
    payload: AssignOrderRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = get_order_detail_for_user(db, user, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")

    try:
        designer_uuid = uuid.UUID(payload.designer_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID")

    designer = db.get(User, designer_uuid)
    if designer is None or not designer.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found or inactive")

    # Update or create assignment
    existing_assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id)
        .one_or_none()
    )
    old_designer_name = None
    if existing_assignment:
        if existing_assignment.designer_id:
            old_des = db.get(User, existing_assignment.designer_id)
            if old_des:
                old_designer_name = old_des.full_name or old_des.username
        existing_assignment.designer_id = designer.id
        existing_assignment.status = "approved"
    else:
        new_assignment = Assignment(
            order_id=order.id,
            designer_id=designer.id,
            status="approved",
        )
        db.add(new_assignment)

    old_state = order.state
    order.state = OrderState.WAITING.value

    des_name = designer.full_name or designer.username
    admin_name = user.full_name or user.username
    is_reassign = existing_assignment is not None and old_designer_name and old_designer_name != des_name
    action_type = "REASSIGN" if is_reassign else "ASSIGN"
    if is_reassign:
        desc = f"Admin {admin_name} phân công lại từ {old_designer_name} sang {des_name} (chuyển về Waiting)"
    else:
        desc = f"Admin {admin_name} phân công đơn cho {des_name} (chuyển về Waiting)"

    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=OrderState.WAITING.value,
        actor_id=user.id,
        evidence={
            "action": action_type,
            "actor_name": admin_name,
            "actor_role": user.role,
            "designer_id": str(designer.id),
            "designer_name": des_name,
            "old_designer_name": old_designer_name,
            "description": desc,
        },
    )
    db.add(event)
    db.commit()

    synced_message = _trigger_printerval_assignment_sync(order, designer)
    return {
        "ok": True,
        "assigned_designer_name": designer.full_name or designer.username,
        "printerval_sync_message": synced_message,
    }


class BulkAssignOrdersRequest(BaseModel):
    order_ids: list[str]
    designer_id: str


@router.post("/orders/bulk-assign")
def api_bulk_assign_orders(
    payload: BulkAssignOrdersRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    if not payload.order_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Danh sách đơn hàng không được để trống")

    try:
        designer_uuid = uuid.UUID(payload.designer_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid designer ID")

    designer = db.get(User, designer_uuid)
    if designer is None or not designer.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer not found or inactive")

    # Fetch orders (accepting either internal UUID or external_order_id)
    valid_uuids = []
    for oid in payload.order_ids:
        try:
            valid_uuids.append(uuid.UUID(oid))
        except ValueError:
            pass

    if valid_uuids:
        orders = db.query(Order).filter(Order.id.in_(valid_uuids)).all()
    else:
        orders = db.query(Order).filter(Order.external_order_id.in_(payload.order_ids)).all()

    if not orders:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng phù hợp")

    updated_count = 0
    des_name = designer.full_name or designer.username
    admin_name = user.full_name or user.username

    for order in orders:
        existing_assignment = (
            db.query(Assignment)
            .filter(Assignment.order_id == order.id)
            .one_or_none()
        )
        old_designer_name = None
        if existing_assignment:
            if existing_assignment.designer_id:
                old_des = db.get(User, existing_assignment.designer_id)
                if old_des:
                    old_designer_name = old_des.full_name or old_des.username
            existing_assignment.designer_id = designer.id
            existing_assignment.status = "approved"
        else:
            new_assignment = Assignment(
                order_id=order.id,
                designer_id=designer.id,
                status="approved",
            )
            db.add(new_assignment)

        old_state = order.state
        order.state = OrderState.WAITING.value
        updated_count += 1

        is_reassign = existing_assignment is not None and old_designer_name and old_designer_name != des_name
        action_type = "REASSIGN" if is_reassign else "ASSIGN"
        if is_reassign:
            desc = f"Admin {admin_name} phân công lại từ {old_designer_name} sang {des_name} (chuyển về Waiting)"
        else:
            desc = f"Admin {admin_name} phân công hàng loạt cho {des_name} (chuyển về Waiting)"

        event = WorkflowEvent(
            order_id=order.id,
            from_state=old_state,
            to_state=OrderState.WAITING.value,
            actor_id=user.id,
            evidence={
                "action": action_type,
                "actor_name": admin_name,
                "actor_role": user.role,
                "designer_id": str(designer.id),
                "designer_name": des_name,
                "old_designer_name": old_designer_name,
                "description": desc,
            },
        )
        db.add(event)

    db.commit()

    message = f"Đã phân công thành công {updated_count} đơn hàng cho {designer.full_name or designer.username}."
    if designer.printerval_designer_option:
        for order in orders:
            _trigger_printerval_assignment_sync(order, designer)
        message += " Đang đồng bộ sang Printerval trong nền (Doing + đổi Designer)."
    else:
        message += (
            " Designer này CHƯA có tên đăng ký trên Printerval nên KHÔNG đồng bộ sang site — chỉ lưu nội bộ."
        )
    return {
        "ok": True,
        "assigned_count": updated_count,
        "designer_name": designer.full_name or designer.username,
        "message": message,
    }


class UpdatePrintervalCredentialsRequest(BaseModel):
    username: str
    password: str | None = None
    team_outsource: str | None = None
    session_cookie: str | None = None


@router.post("/orders/printerval-credentials")
def api_update_printerval_credentials(
    payload: UpdatePrintervalCredentialsRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    from app.application.platform_credentials import (
        PlatformCredentialsError,
        ensure_platform_for_account,
        verify_and_save_platform_credentials,
    )

    # Backward-compatible deprecated route. New clients use
    # PATCH /platforms/{platform_id}/credentials so credentials always target a known
    # platform rather than being hidden under the orders resource.
    platform = ensure_platform_for_account(db, payload.username)
    try:
        platform = verify_and_save_platform_credentials(
            db,
            platform=platform,
            username=payload.username,
            password=payload.password,
            team_outsource=payload.team_outsource,
            session_cookie=payload.session_cookie,
        )
    except PlatformCredentialsError as exc:
        # `ensure_platform_for_account` may have flushed a newly-created platform
        # before live credential verification. Do not leave that unusable row behind
        # when verification fails.
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "ok": True,
        "platform_id": str(platform.id),
        "platform_name": platform.name,
        "account_username": platform.account_username,
        "message": f"Đã đăng nhập tài khoản Printerval thành công: {platform.account_username}",
    }


class UpdateOrderStateRequest(BaseModel):
    state: str
    drive_url: str | None = None
    note_outsource: str | None = None


class DesignerNoteRequest(BaseModel):
    designer_note: str = ""


def _get_order_by_identifier(db: Session, order_id: str) -> Order | None:
    try:
        order = db.get(Order, uuid.UUID(order_id))
    except ValueError:
        order = None
    return order or db.query(Order).filter(Order.external_order_id == order_id).first()


@router.put("/orders/{order_id}/designer-note")
def api_update_designer_note(
    order_id: str,
    payload: DesignerNoteRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = _get_order_by_identifier(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    order.designer_note = payload.designer_note.strip()
    db.add(WorkflowEvent(
        order_id=order.id, from_state=order.state, to_state=order.state, actor_id=user.id,
        evidence={"action": "UPDATE_DESIGNER_NOTE", "actor_role": "admin", "actor_name": user.full_name or user.username,
                  "description": "Admin cập nhật ghi chú gửi Designer."},
    ))
    db.commit()
    return {"ok": True, "designer_note": order.designer_note}


@router.post("/orders/{order_id}/resolve-missing-template")
def api_resolve_missing_template(
    order_id: str,
    payload: DesignerNoteRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = _get_order_by_identifier(db, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    if not order.template_missing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Đơn này không nằm trong danh sách thiếu temp")

    assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status == "approved")
        .order_by(Assignment.created_at.desc())
        .first()
    )
    if assignment is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Đơn thiếu assignment đang hoạt động")

    old_state = order.state
    order.designer_note = payload.designer_note.strip()
    order.template_missing = False
    order.template_missing_reported_at = None
    order.template_missing_reported_by_id = None
    assignment.sub_status = "todo"
    if order.state != OrderState.IN_PROGRESS.value:
        apply_transition(
            db, order, OrderState.IN_PROGRESS, actor_id=user.id,
            evidence={"action": "RESOLVE_MISSING_TEMPLATE", "actor_role": "admin", "actor_name": user.full_name or user.username,
                      "description": "Admin đã bổ sung temp/ghi chú và trả đơn về Doing cho Designer."},
            commit=False,
        )
    else:
        db.add(WorkflowEvent(
            order_id=order.id, from_state=old_state, to_state=OrderState.IN_PROGRESS.value, actor_id=user.id,
            evidence={"action": "RESOLVE_MISSING_TEMPLATE", "actor_role": "admin", "actor_name": user.full_name or user.username,
                      "description": "Admin đã bổ sung temp/ghi chú và trả đơn về Doing cho Designer."},
        ))
    db.commit()
    return {"ok": True, "state": order.state, "designer_note": order.designer_note}


@router.patch("/orders/{order_id}/state")
def api_update_order_state(
    order_id: str,
    payload: UpdateOrderStateRequest,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    raw_state = payload.state.strip().upper()
    state_mapping = {
        "WAITING": OrderState.WAITING,
        "ASSIGNED": OrderState.WAITING,
        "DOING": OrderState.IN_PROGRESS,
        "IN_PROGRESS": OrderState.IN_PROGRESS,
        "REVIEW": OrderState.QC_PENDING,
        "QC_PENDING": OrderState.QC_PENDING,
        "FIX": OrderState.REVISION,
        "REVISION": OrderState.REVISION,
        "DONE": OrderState.DONE,
    }
    if raw_state not in state_mapping:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Trạng thái không hợp lệ: {payload.state}. Chỉ chấp nhận Waiting, Doing, Review, Fix, Done.",
        )
    target_state = state_mapping[raw_state]

    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        expected_domain = (
            WORK_DOMAIN_DUPLICATE if user.role == ROLE_DESIGNER_TRELLO else WORK_DOMAIN_STANDARD
        )
        if order.work_domain != expected_domain:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Bạn chỉ có thể cập nhật đơn thuộc phạm vi công việc của mình.",
            )
        if is_unreleased_fix(order):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Đơn Fix đang chờ Admin chấp nhận và giao lại; bạn chưa thể thao tác.",
            )
        if target_state not in (OrderState.WAITING, OrderState.IN_PROGRESS, OrderState.QC_PENDING):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Designer chỉ có quyền chuyển đơn sang Waiting, Doing (Đang làm) hoặc Review (Chờ duyệt). Chỉ Admin mới có quyền duyệt Done hoặc yêu cầu Fix.",
            )
        is_assigned = (
            db.query(Assignment)
            .filter(
                Assignment.order_id == order.id,
                Assignment.designer_id == user.id,
                Assignment.status != "cancelled",
            )
            .first()
            is not None
        )
        is_printerval_assigned = (
            bool(user.printerval_designer_option and order.printerval_designer == user.printerval_designer_option)
            or bool(user.full_name and order.printerval_designer == user.full_name)
        )
        if not (is_assigned or is_printerval_assigned):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Bạn chỉ có thể cập nhật trạng thái các đơn hàng được phân công cho bạn.",
            )

    old_state = order.state
    order.state = target_state.value
    order.status_changed_at = datetime.now(UTC)

    submitted_link = (payload.drive_url or "").strip()
    submitted_note = (payload.note_outsource or "").strip()
    if submitted_link:
        order.note_outsource = submitted_link
    elif submitted_note:
        order.note_outsource = submitted_note

    actor_name = user.full_name or user.username
    des_name = None
    curr_assignment = (
        db.query(Assignment)
        .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
        .first()
    )
    if curr_assignment and curr_assignment.designer_id:
        des_user = db.get(User, curr_assignment.designer_id)
        if des_user:
            des_name = des_user.full_name or des_user.username
    if not des_name and order.printerval_designer:
        des_name = order.printerval_designer

    # Record submitted version if drive link provided
    if submitted_link and curr_assignment:
        v_count = db.query(ResultVersion).filter(ResultVersion.assignment_id == curr_assignment.id).count()
        rv = ResultVersion(
            assignment_id=curr_assignment.id,
            drive_url=submitted_link,
            version_marker=v_count + 1,
            submitted_at=datetime.now(UTC),
            validated=True,
        )
        db.add(rv)

    actor_disp = f"{'Designer ' if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO) else ('Admin ' if user.role == ROLE_ADMIN else '')}{actor_name}"
    if target_state == OrderState.IN_PROGRESS:
        if old_state in (OrderState.QC_PENDING.value, "REVIEW"):
            action_type = "REVERT_TO_DOING"
            desc = f"{actor_disp} chuyển lại về Doing để chỉnh sửa bài"
        else:
            action_type = "START_DOING"
            desc = f"{actor_disp} nhận đơn vào Doing"
    elif target_state == OrderState.QC_PENDING:
        order.fix_approved_by_admin = False
        order.fix_rejected_by_admin = False
        if old_state in (OrderState.REVISION.value, "FIX", "REVISION_REQUESTED"):
            action_type = "RESUBMIT_FIX"
            desc = f"{actor_disp} nộp lại bài sau khi fix"
        else:
            action_type = "SUBMIT_REVIEW"
            desc = f"{actor_disp} nộp bài sang Review"
        # Sync Review status & Note outsource to Printerval
        try:
            from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task
            sync_order_review_to_printerval_task.delay(
                str(order.id),
                order.note_outsource,
                "Review",
                expected_state=OrderState.QC_PENDING.value,
                expected_fix_approved=False,
            )
        except Exception:
            pass
    elif target_state == OrderState.REVISION:
        action_type = "REQUEST_FIX"
        desc = f"{actor_disp} yêu cầu sửa bài (Fix)"
        order.fix_approved_by_admin = False
        order.fix_rejected_by_admin = False
    elif target_state == OrderState.DONE:
        action_type = "APPROVE_DONE"
        desc = f"{actor_disp} duyệt hoàn thành đơn hàng (Done)"
    elif target_state == OrderState.WAITING:
        action_type = "SET_WAITING"
        desc = f"{actor_disp} chuyển đơn về Waiting"
    else:
        action_type = "CHANGE_STATE"
        from_lbl = get_friendly_state_label(old_state)
        to_lbl = get_friendly_state_label(target_state.value)
        desc = f"{actor_disp}: {from_lbl} → {to_lbl}"

    evidence_payload = {
        "action": action_type,
        "actor_name": actor_name,
        "actor_role": user.role,
        "designer_name": des_name,
        "description": desc,
        "source": "status_update",
    }
    if submitted_link:
        evidence_payload["drive_link"] = submitted_link
    elif order.note_outsource:
        evidence_payload["drive_link"] = order.note_outsource

    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=target_state.value,
        actor_id=user.id,
        evidence=evidence_payload,
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "state": order.state,
        "note_outsource": order.note_outsource,
        "message": f"Đã chuyển trạng thái đơn {order.external_order_id} sang {target_state.value}",
    }


class ApproveFixRequest(BaseModel):
    designer_id: uuid.UUID | None = None
    designer_note: str | None = None
    note_outsource: str | None = None


@router.post("/orders/{order_id}/approve-fix")
def api_approve_fix(
    order_id: str,
    payload: ApproveFixRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    if payload.designer_note is not None:
        order.designer_note = payload.designer_note.strip()
    if payload.note_outsource is not None:
        order.note_outsource = payload.note_outsource.strip()

    assigned_designer_name = None
    if payload.designer_id:
        target_des = db.get(User, payload.designer_id)
        if target_des:
            assigned_designer_name = target_des.full_name or target_des.username
            curr_assignment = (
                db.query(Assignment)
                .filter(Assignment.order_id == order.id, Assignment.status != "cancelled")
                .first()
            )
            if curr_assignment:
                curr_assignment.designer_id = target_des.id
                curr_assignment.status = "approved"
            else:
                db.add(Assignment(order_id=order.id, designer_id=target_des.id, status="approved"))

    order.state = OrderState.REVISION.value
    order.fix_approved_by_admin = True
    order.status_changed_at = datetime.now(UTC)

    admin_name = user.full_name or user.username
    desc = f"Admin {admin_name} chấp nhận Fix & giao bài cho {assigned_designer_name or 'Designer'}"
    if order.designer_note:
        desc += f" (Note Des: {order.designer_note})"

    event = WorkflowEvent(
        order_id=order.id,
        from_state=OrderState.REVISION.value,
        to_state=OrderState.REVISION.value,
        actor_id=user.id,
        evidence={
            "action": "APPROVE_FIX_FOR_DESIGNER",
            "actor_name": admin_name,
            "actor_role": user.role,
            "designer_name": assigned_designer_name,
            "description": desc,
            "designer_note": order.designer_note,
            "note_outsource": order.note_outsource,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "fix_approved_by_admin": True,
        "designer_note": order.designer_note,
        "note_outsource": order.note_outsource,
        "message": "Đã chấp nhận Fix và giao bài cho Designer.",
    }


class RejectFixRequest(BaseModel):
    note_outsource: str | None = None


@router.post("/orders/{order_id}/reject-fix-to-review")
def api_reject_fix_to_review(
    order_id: str,
    payload: RejectFixRequest,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    order.previous_note_outsource = order.note_outsource
    if payload.note_outsource is not None:
        order.note_outsource = payload.note_outsource.strip()

    old_state = order.state
    # The admin rejected Printerval's Fix request. The card is therefore waiting
    # for QC review locally too; retaining REVISION here stranded it in the Fix tab.
    order.state = OrderState.QC_PENDING.value
    order.fix_approved_by_admin = False
    order.fix_rejected_by_admin = True
    order.status_changed_at = datetime.now(UTC)

    admin_name = user.full_name or user.username
    event = WorkflowEvent(
        order_id=order.id,
        from_state=old_state,
        to_state=OrderState.QC_PENDING.value,
        actor_id=user.id,
        evidence={
            "action": "REJECT_FIX_TO_REVIEW",
            "actor_name": admin_name,
            "actor_role": user.role,
            "description": f"Admin {admin_name} từ chối Fix và gửi lại Review trên Printerval",
            "note_outsource": order.note_outsource,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(order)

    # Sync to Printerval in background
    try:
        from app.workers.assignment_sync_tasks import sync_order_review_to_printerval_task
        sync_order_review_to_printerval_task.delay(
            str(order.id),
            order.note_outsource,
            "Review",
            expected_state=OrderState.QC_PENDING.value,
            expected_fix_approved=False,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "order_id": str(order.id),
        "external_order_id": order.external_order_id,
        "state": order.state,
        "note_outsource": order.note_outsource,
        "fix_approved_by_admin": order.fix_approved_by_admin,
        "fix_rejected_by_admin": order.fix_rejected_by_admin,
        "message": "Đã hủy Fix, cập nhật note outsource và chuyển lại trạng thái Review trên Printerval.",
    }


class SyncPrintervalStatusPayload(BaseModel):
    order_ids: list[str] | None = None
    state: str | None = None


@router.post("/orders/sync-printerval-status")
@router.post("/orders/sync-platform-status")
def api_sync_printerval_status(
    payload: SyncPrintervalStatusPayload,
    user: User = Depends(get_current_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    from app.application.status_sync import sync_selected_order_statuses

    platform = db.get(Platform, platform_id)
    if platform is None or not (platform.account_username and (platform.account_password or platform.session_cookie)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Chưa cấu hình tài khoản hoặc cookie Printerval cho platform hiện tại.",
        )

    # Build query for target orders
    query = db.query(Order).filter(Order.platform_id == platform_id)
    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        asgn_order_ids = (
            db.query(Assignment.order_id)
            .filter(Assignment.designer_id == user.id, Assignment.status != "cancelled")
        )
        expected_domain = (
            WORK_DOMAIN_DUPLICATE if user.role == ROLE_DESIGNER_TRELLO else WORK_DOMAIN_STANDARD
        )
        query = query.filter(
            Order.work_domain == expected_domain,
            or_(Order.state.not_in(FIX_STATES), Order.fix_approved_by_admin.is_(True)),
            or_(
                Order.id.in_(asgn_order_ids),
                Order.printerval_designer == user.printerval_designer_option,
                Order.printerval_designer == user.full_name,
            )
        )

    if payload.order_ids:
        raw_ids = [s.strip() for s in payload.order_ids if s.strip()]
        u_ids = []
        ext_ids = []
        for rid in raw_ids:
            try:
                u_ids.append(uuid.UUID(rid))
            except ValueError:
                ext_ids.append(rid)
        query = query.filter(or_(Order.id.in_(u_ids), Order.external_order_id.in_(ext_ids)))
    elif payload.state:
        st = payload.state.strip().upper()
        if st in ("REVIEW", "QC_PENDING"):
            query = query.filter(Order.state == OrderState.QC_PENDING.value)
        elif st in ("FIX", "REVISION"):
            query = query.filter(Order.state == OrderState.REVISION.value)
        elif st in ("DOING", "IN_PROGRESS"):
            query = query.filter(Order.state == OrderState.IN_PROGRESS.value)
        elif st in ("WAITING", "ASSIGNED"):
            query = query.filter(Order.state.in_([OrderState.WAITING.value, "ASSIGNED"]))
        elif st == "TODO":
            query = query.filter(
                or_(
                    Order.state.in_([OrderState.WAITING.value, "ASSIGNED"]),
                    (Order.state.in_([OrderState.REVISION.value, "FIX"]) & (Order.fix_approved_by_admin.is_(True))),
                )
            )

    orders = query.all()
    if not orders:
        return {"ok": True, "checked_count": 0, "updated_count": 0, "message": "Không có đơn hàng nào cần kiểm tra."}

    result = sync_selected_order_statuses(db, platform, orders, actor_id=user.id)

    return {
        "ok": True,
        "checked_count": result["checked"],
        "updated_count": result["updated"],
        "not_found_count": result["not_found"],
        "failed_count": result["failed"],
        "message": (
            f"Đã kiểm tra {result['checked']} đơn trong tab, cập nhật {result['updated']} thay đổi"
            f"; không tìm thấy {result['not_found']}; lỗi {result['failed']}."
        ),
    }


class DesignerWorkloadOrderOut(BaseModel):
    id: str
    external_order_id: str
    state: str
    thumbnail_url: str | None = None
    product_image_urls: list[str] | None = None
    deadline_at_ext: str | None = None
    product_name: str | None = None
    work_domain: str = "standard"
    printerval_designer: str | None = None
    platform_designer: str | None = None
    note_outsource: str = ""
    previous_note_outsource: str | None = None
    fix_approved_by_admin: bool = False
    fix_return_count: int = 0


class DesignerWorkloadOut(BaseModel):
    id: str
    username: str
    full_name: str
    printerval_designer_option: str | None = None
    platform_designer_option: str | None = None
    total_orders: int
    waiting_count: int = 0
    doing_count: int
    review_count: int
    fix_count: int
    done_count: int
    orders: list[DesignerWorkloadOrderOut]


@router.get("/designers/workload", response_model=list[DesignerWorkloadOut])
def api_designers_workload(
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    designers = (
        db.query(User)
        .filter(
            User.role.in_([ROLE_DESIGNER, ROLE_DESIGNER_TRELLO]),
            User.active.is_(True),
            (User.platform_id == platform_id) | (User.platform_id.is_(None)),
        )
        .order_by(User.full_name)
        .all()
    )

    platform_orders = (
        db.query(Order)
        .filter(Order.platform_id == platform_id)
        .order_by(Order.created_at.desc())
        .all()
    )

    assignments = (
        db.query(Assignment)
        .filter(Assignment.status.in_(["approved", "draft"]))
        .order_by(Assignment.created_at.asc())
        .all()
    )
    order_designer_assignment = {a.order_id: a.designer_id for a in assignments}

    results = []
    for des in designers:
        des_orders = []
        for o in platform_orders:
            assigned_des_id = order_designer_assignment.get(o.id)
            is_match = (
                (assigned_des_id == des.id)
                or (des.printerval_designer_option and o.printerval_designer == des.printerval_designer_option)
                or (des.full_name and o.printerval_designer == des.full_name)
            )
            if is_match:
                des_orders.append(o)

        waiting_count = sum(1 for o in des_orders if o.state in ("WAITING", "OPEN"))
        doing_count = sum(1 for o in des_orders if o.state in ("IN_PROGRESS", "ASSIGNED") and o.state != "WAITING")
        review_count = sum(1 for o in des_orders if o.state in ("QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE"))
        fix_count = sum(1 for o in des_orders if o.state in ("REVISION", "REVISION_REQUESTED"))
        done_count = sum(1 for o in des_orders if o.state in ("DONE", "SKIPPED"))

        def state_priority(s: str) -> int:
            if s in ("QC_PENDING", "RESULT_SUBMITTED"):
                return 0
            if s in ("REVISION", "REVISION_REQUESTED"):
                return 1
            if s == "IN_PROGRESS":
                return 2
            if s in ("WAITING", "OPEN"):
                return 3
            return 4

        des_orders.sort(key=lambda x: (state_priority(x.state), -(x.created_at.timestamp() if x.created_at else 0)))

        results.append(
            DesignerWorkloadOut(
                id=str(des.id),
                username=des.username,
                full_name=des.full_name or des.username,
                printerval_designer_option=des.printerval_designer_option,
                platform_designer_option=des.printerval_designer_option,
                total_orders=len(des_orders),
                waiting_count=waiting_count,
                doing_count=doing_count,
                review_count=review_count,
                fix_count=fix_count,
                done_count=done_count,
                orders=[
                    DesignerWorkloadOrderOut(
                        id=str(o.id),
                        external_order_id=o.external_order_id,
                        state=o.state,
                        thumbnail_url=o.thumbnail_url,
                        product_image_urls=(
                            o.product_image_urls
                            if o.product_image_urls
                            else ([o.thumbnail_url] if o.thumbnail_url else None)
                        ),
                        deadline_at_ext=str(o.deadline_at_ext) if o.deadline_at_ext else None,
                        product_name=o.product_name,
                        work_domain=o.work_domain or "standard",
                        printerval_designer=o.printerval_designer,
                        platform_designer=o.printerval_designer,
                        note_outsource=o.note_outsource or "",
                        previous_note_outsource=o.previous_note_outsource,
                        fix_approved_by_admin=o.fix_approved_by_admin,
                        fix_return_count=o.fix_return_count,
                    )
                    for o in des_orders
                ],
            )
        )

    return results


@router.get("/orders-history", response_model=OrderHistoryListResponse)
def api_get_orders_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    search: str | None = None,
    order_id: str | None = None,
    designer_id: str | None = None,
    action: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(WorkflowEvent, Order)
        .join(Order, Order.id == WorkflowEvent.order_id)
    )

    header_platform_id = request.headers.get("X-Platform-Id")
    if header_platform_id and header_platform_id != "ALL":
        try:
            p_uuid = uuid.UUID(header_platform_id)
            if p_uuid != DEFAULT_PLATFORM_ID:
                query = query.filter(Order.platform_id == p_uuid)
        except ValueError:
            pass

    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        asgn_order_ids = (
            db.query(Assignment.order_id)
            .filter(Assignment.designer_id == user.id, Assignment.status != "cancelled")
        )
        expected_domain = (
            WORK_DOMAIN_DUPLICATE if user.role == ROLE_DESIGNER_TRELLO else WORK_DOMAIN_STANDARD
        )
        query = query.filter(
            Order.work_domain == expected_domain,
            or_(Order.state.not_in(FIX_STATES), Order.fix_approved_by_admin.is_(True)),
            or_(
                Order.id.in_(asgn_order_ids),
                Order.printerval_designer == user.printerval_designer_option,
                Order.printerval_designer == user.full_name,
            )
        )

    if order_id and order_id.strip():
        clean_oid = order_id.strip()
        try:
            o_uuid = uuid.UUID(clean_oid)
            query = query.filter(Order.id == o_uuid)
        except ValueError:
            query = query.filter(Order.external_order_id.ilike(f"%{clean_oid}%"))

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Order.external_order_id.ilike(term),
                Order.product_name.ilike(term),
                WorkflowEvent.from_state.ilike(term),
                WorkflowEvent.to_state.ilike(term),
                WorkflowEvent.evidence["description"].astext.ilike(term),
                WorkflowEvent.evidence["actor_name"].astext.ilike(term),
                WorkflowEvent.evidence["designer_name"].astext.ilike(term),
            )
        )

    if action and action.strip() and action != "ALL":
        query = query.filter(WorkflowEvent.evidence["action"].astext == action.strip())

    if designer_id and designer_id.strip() and designer_id != "ALL":
        try:
            d_uuid = uuid.UUID(designer_id.strip())
            d_user = db.get(User, d_uuid)
            if d_user:
                d_name = d_user.full_name or d_user.username
                query = query.filter(
                    or_(
                        WorkflowEvent.evidence["designer_id"].astext == str(d_uuid),
                        WorkflowEvent.evidence["designer_name"].astext == d_name,
                        WorkflowEvent.actor_id == d_uuid,
                    )
                )
        except ValueError:
            pass

    total = query.count()
    offset = (page - 1) * page_size
    results = query.order_by(WorkflowEvent.created_at.desc()).offset(offset).limit(page_size).all()

    actor_ids = {event.actor_id for event, _ in results if event.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    items = []
    for event, order in results:
        actor_info = actors_map.get(event.actor_id)
        actor_name = (event.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (event.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action_type = (event.evidence or {}).get("action")
        designer_name = (event.evidence or {}).get("designer_name")
        desc = format_event_description(
            from_state=event.from_state,
            to_state=event.to_state,
            action=action_type,
            actor_name=actor_name,
            actor_role=actor_role,
            designer_name=designer_name,
            raw_desc=(event.evidence or {}).get("description"),
        )

        items.append(
            OrderHistoryItemOut(
                id=str(event.id),
                created_at=event.created_at,
                order_id=str(order.id),
                external_order_id=order.external_order_id,
                product_name=order.product_name,
                thumbnail_url=order.thumbnail_url,
                from_state=event.from_state,
                to_state=event.to_state,
                actor_id=str(event.actor_id) if event.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action_type,
                description=desc,
                designer_name=designer_name,
                evidence=event.evidence,
            )
        )

    total_pages = max(1, math.ceil(total / page_size))
    return OrderHistoryListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/orders/{order_id}/history", response_model=list[WorkflowEventOut])
def api_get_single_order_history(
    order_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    order = None
    try:
        order_uuid = uuid.UUID(order_id)
        order = db.get(Order, order_uuid)
    except ValueError:
        pass
    if order is None:
        order = db.query(Order).filter(Order.external_order_id == order_id).first()

    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    # Reuse the same authorization gate as the detail page. This also hides a
    # Printerval Fix until Admin explicitly releases it, and applies to Trello
    # designers as well as regular designers.
    if user.role in (ROLE_DESIGNER, ROLE_DESIGNER_TRELLO):
        if get_order_detail_for_user(db, user, str(order.id)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")

    history = get_order_history(db, str(order.id))
    actor_ids = {e.actor_id for e in history if e.actor_id}
    actors_map = {}
    if actor_ids:
        users = db.query(User).filter(User.id.in_(actor_ids)).all()
        actors_map = {u.id: (u.full_name or u.username, u.role) for u in users}

    history_out = []
    for e in history:
        actor_info = actors_map.get(e.actor_id)
        actor_name = (e.evidence or {}).get("actor_name") or (actor_info[0] if actor_info else None)
        actor_role = (e.evidence or {}).get("actor_role") or (actor_info[1] if actor_info else None)
        action = (e.evidence or {}).get("action")
        designer_name = (e.evidence or {}).get("designer_name")
        description = format_event_description(
            from_state=e.from_state,
            to_state=e.to_state,
            action=action,
            actor_name=actor_name,
            actor_role=actor_role,
            designer_name=designer_name,
            raw_desc=(e.evidence or {}).get("description"),
        )

        history_out.append(
            WorkflowEventOut(
                id=str(e.id),
                created_at=e.created_at,
                from_state=e.from_state,
                to_state=e.to_state,
                actor_id=str(e.actor_id) if e.actor_id else None,
                actor_name=actor_name,
                actor_role=actor_role,
                action=action,
                description=description,
                designer_name=designer_name,
                evidence=e.evidence,
            )
        )

    is_admin = user.role == ROLE_ADMIN
    if not is_admin:
        history_out = [sanitize_workflow_event_for_designer(ev) for ev in history_out]

    return history_out


class BulkDeleteOrdersPayload(BaseModel):
    order_ids: list[str]


@router.post("/orders/bulk-delete")
def api_bulk_delete_orders(
    payload: BulkDeleteOrdersPayload,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Admin endpoint to permanently delete selected orders and their cascades from database."""
    if not payload.order_ids:
        return {"ok": True, "deleted_count": 0}

    parsed_ids = []
    for oid in payload.order_ids:
        try:
            parsed_ids.append(uuid.UUID(oid))
        except ValueError:
            pass

    if not parsed_ids:
        return {"ok": True, "deleted_count": 0}

    orders = db.query(Order).filter(Order.id.in_(parsed_ids), Order.platform_id == platform_id).all()
    valid_ids = [o.id for o in orders]
    if not valid_ids:
        return {"ok": True, "deleted_count": 0}

    # 1. Delete FinanceNotes
    db.query(FinanceNote).filter(FinanceNote.order_id.in_(valid_ids)).delete(synchronize_session=False)

    # 2. Gather assignments & result versions
    assignments = db.query(Assignment).filter(Assignment.order_id.in_(valid_ids)).all()
    asgn_ids = [a.id for a in assignments]

    rv_ids = []
    if asgn_ids:
        result_versions = db.query(ResultVersion).filter(ResultVersion.assignment_id.in_(asgn_ids)).all()
        rv_ids = [rv.id for rv in result_versions]

    # 3. Delete ApprovalDecisions & ApprovalRequests linked to ResultVersions, Assignments, or Orders
    approval_reqs_filter = []
    if rv_ids:
        approval_reqs_filter.append(ApprovalRequest.target_version_id.in_(rv_ids))
    if asgn_ids:
        approval_reqs_filter.append(ApprovalRequest.target_id.in_(asgn_ids))
    approval_reqs_filter.append(ApprovalRequest.target_id.in_(valid_ids))

    approval_reqs = db.query(ApprovalRequest).filter(or_(*approval_reqs_filter)).all()
    ar_ids = [ar.id for ar in approval_reqs]
    if ar_ids:
        db.query(ApprovalDecision).filter(ApprovalDecision.approval_request_id.in_(ar_ids)).delete(synchronize_session=False)
        db.query(ApprovalRequest).filter(ApprovalRequest.id.in_(ar_ids)).delete(synchronize_session=False)

    # 4. Delete ResultVersions
    if rv_ids:
        db.query(ResultVersion).filter(ResultVersion.id.in_(rv_ids)).delete(synchronize_session=False)

    # 5. Delete Assignments (clear replacement_of_id self references first)
    if asgn_ids:
        db.query(Assignment).filter(Assignment.id.in_(asgn_ids)).update({"replacement_of_id": None}, synchronize_session=False)
        db.query(Assignment).filter(Assignment.id.in_(asgn_ids)).delete(synchronize_session=False)

    # 6. Delete WorkflowEvents
    db.query(WorkflowEvent).filter(WorkflowEvent.order_id.in_(valid_ids)).delete(synchronize_session=False)

    # 7. Delete ExternalObservations
    db.query(ExternalObservation).filter(ExternalObservation.order_id.in_(valid_ids)).delete(synchronize_session=False)

    # 8. Delete OrderAssets
    db.query(OrderAsset).filter(OrderAsset.order_id.in_(valid_ids)).delete(synchronize_session=False)

    # 9. Delete PrintervalAssignmentRequests
    db.query(PrintervalAssignmentRequest).filter(PrintervalAssignmentRequest.order_id.in_(valid_ids)).delete(synchronize_session=False)

    # 10. Delete Orders
    db.query(Order).filter(Order.id.in_(valid_ids)).delete(synchronize_session=False)

    db.commit()
    return {"ok": True, "deleted_count": len(valid_ids)}


@router.post("/orders/{order_id}/revoke-assignment")
def revoke_single_order_assignment(
    order_id: uuid.UUID,
    user: User = Depends(require_role("admin")),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        revoke_assignment_command(
            db,
            platform_id=platform_id,
            actor=user,
            order_ids=[order_id],
        )
    except AssignmentCommandError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"ok": True, "message": "Đã hủy chia đơn thành công, đơn đã quay về trạng thái Waiting."}
