"""Support review of duplicate-image comparison jobs, the job queue and image search.

Ported from the former localhost review server: it now lives next to the rest of the web
API (session auth, platform scoping). Reviewing only writes ``support_compare_image`` rows;
orders are never touched here. The DINO work itself is done by Support machines through
``support_worker_api``.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, OrderWorkNote, SupportCompareJob, SupportSearchJob, User
from app.api.deps import get_current_platform_id, get_db, require_any_role
from app.application import support_review_access as access_svc
from app.application import support_worker as sw
from app.application.duplicate_board import DuplicateBoardError
from app.application.order_work_notes import create_work_note
from app.application.support_compare import (
    STAGES,
    item_stage,
    lot_stage_rows,
    send_lot_pairs,
    tag_lot_orders,
)
from app.domain.access import (
    DUPLICATE_CHECK_DUPLICATE,
    DUPLICATE_CHECK_NON_DUPLICATE,
    ROLE_ADMIN,
    ROLE_SUPPORT,
    SUPPORT_CLASSIFICATION_STATES,
)

S = "support_compare_image"
# States in which the reviewer may still change the decision. Once the pair was sent to
# Telegram (telegram_notified_at set) the choice is frozen.
REVIEWABLE = ("pending_review", "ai_wrong", "selected_duplicate")
# Picking a duplicate is also allowed from "no_match": the model may have missed it.
SELECTABLE = (*REVIEWABLE, "no_match")
MAX_UPLOAD_BYTES = 10_000_000

router = APIRouter(prefix="/support-review")
_user = require_any_role(ROLE_SUPPORT)


def require_unlock(
    request: Request,
    user: User = Depends(_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> User:
    """The review area is hidden behind its own password (X-Review-Token from /access/unlock)."""
    if not access_svc.token_is_valid(db, user, platform_id, request.headers.get("x-review-token")):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "review_locked", "message": "Cần nhập mật khẩu để mở giao diện duyệt trùng."},
        )
    return user


def _access_error(exc: access_svc.ReviewAccessError) -> HTTPException:
    return HTTPException(exc.status_code, {"code": exc.code, "message": exc.message})


class PasswordIn(BaseModel):
    password: str = Field(max_length=access_svc.MAX_PASSWORD_LENGTH)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=access_svc.MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=access_svc.MAX_PASSWORD_LENGTH)


@router.get("/access")
def access_status(
    request: Request,
    user: User = Depends(_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    has_password = access_svc.get_access(db, platform_id) is not None
    unlocked = has_password and access_svc.token_is_valid(db, user, platform_id, request.headers.get("x-review-token"))
    return {"has_password": has_password, "unlocked": unlocked}


@router.post("/access/setup")
def access_setup(
    payload: PasswordIn,
    user: User = Depends(_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        token = access_svc.set_initial_password(db, user=user, platform_id=platform_id, password=payload.password)
    except access_svc.ReviewAccessError as exc:
        raise _access_error(exc) from exc
    db.commit()
    return {"token": token}


@router.post("/access/unlock")
def access_unlock(
    payload: PasswordIn,
    user: User = Depends(_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        token = access_svc.unlock(db, user=user, platform_id=platform_id, password=payload.password)
    except access_svc.ReviewAccessError as exc:
        raise _access_error(exc) from exc
    db.commit()
    return {"token": token}


@router.post("/access/change")
def access_change(
    payload: ChangePasswordIn,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        token = access_svc.change_password(
            db, user=user, platform_id=platform_id, current=payload.current_password, new=payload.new_password
        )
    except access_svc.ReviewAccessError as exc:
        raise _access_error(exc) from exc
    db.commit()
    return {"token": token}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- image proxy

IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_IMAGE_BYTES = 25_000_000


def _is_public_host(host: str) -> bool:
    """Image URLs come from customer data: never let the proxy reach private/loopback addresses."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # follow redirects by hand, validating each hop
        return None


def _fetch_image(url: str, hops: int = 3) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or not _is_public_host(parsed.hostname):
        raise HTTPException(400, "URL ảnh không hợp lệ")
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": IMAGE_USER_AGENT, "Accept": "image/*,*/*;q=0.8"})
    try:
        with opener.open(req, timeout=15) as resp:
            content_type = resp.headers.get_content_type()
            if not content_type.startswith("image/"):
                raise HTTPException(415, "Không phải ảnh")
            data = resp.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308) and hops > 0 and exc.headers.get("Location"):
            return _fetch_image(urljoin(url, exc.headers["Location"]), hops - 1)
        raise HTTPException(502, f"Nguồn ảnh trả về {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise HTTPException(502, "Không tải được ảnh từ nguồn") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Ảnh quá lớn")
    return data, content_type


@router.get("/img")
def proxy_image(url: str, _user_: User = Depends(require_unlock)) -> Response:
    """Serve a product image through the API: same headers as the worker (no Referer, browser
    User-Agent) so hotlink protection on third-party CDNs does not break it."""
    data, content_type = _fetch_image(url)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})


# --------------------------------------------------------------------------- jobs


class SelectBody(BaseModel):
    candidate_id: uuid.UUID


_JOB_COLUMNS = (
    "id", "status", "requested_count", "processed_count", "duplicate_count", "error_count",
    "run_id", "created_at", "finished_at",
)


def _job_row(row: Any) -> dict[str, Any]:
    out = dict(zip(_JOB_COLUMNS, row[: len(_JOB_COLUMNS)]))
    for key in ("id", "run_id"):
        out[key] = str(out[key]) if out[key] else None
    for key in ("created_at", "finished_at"):
        out[key] = _iso(out[key])
    return out


@router.get("/jobs")
def list_jobs(
    limit: int = 15,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.execute(
        text(
            f"""SELECT id, status, requested_count, processed_count, duplicate_count,
                       error_count, run_id, created_at, finished_at
                FROM {S}.comparison_jobs WHERE platform_id = :pid
                ORDER BY created_at DESC LIMIT :limit"""
        ),
        {"pid": platform_id, "limit": max(1, min(limit, 50))},
    ).fetchall()
    jobs = [_job_row(r) for r in rows]
    run_ids = [uuid.UUID(j["run_id"]) for j in jobs if j["run_id"]]
    counts: dict[str, dict[str, int]] = {}
    for run_id, _order, _code, stage, _tag, _state in lot_stage_rows(db, run_ids):
        counts.setdefault(str(run_id), dict.fromkeys(STAGES, 0))[stage] += 1
    for job in jobs:
        job["stages"] = counts.get(job["run_id"] or "", dict.fromkeys(STAGES, 0))
    return {"jobs": jobs}


def _get_job_or_404(db: Session, job_id: uuid.UUID, platform_id: uuid.UUID) -> SupportCompareJob:
    job = db.get(SupportCompareJob, job_id)
    if job is None or job.platform_id != platform_id:
        raise HTTPException(404, "Không tìm thấy job")
    return job


@router.get("/jobs/{job_id}")
def get_job(
    job_id: uuid.UUID,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = _get_job_or_404(db, job_id, platform_id)
    out = _job_row(
        (
            job.id, job.status, job.requested_count, job.processed_count, job.duplicate_count,
            job.error_count, job.run_id, job.created_at, job.finished_at,
        )
    )
    items: list[dict[str, Any]] = []
    if job.run_id:
        item_rows = db.execute(
            text(
                f"""SELECT i.id, i.external_order_id, i.product_name, i.image_url, i.is_duplicate,
                           i.review_status, i.selected_candidate_id, i.reviewed_at, o.custom_config,
                           i.order_id, o.duplicate_check_status, sc.decision_status, sc.telegram_notified_at,
                           o.state
                    FROM {S}.comparison_items i
                    LEFT JOIN public.orders o ON o.id = i.order_id
                    LEFT JOIN {S}.comparison_candidates sc ON sc.id = i.selected_candidate_id
                    WHERE i.run_id = :run AND i.processing_status = 'completed'
                    ORDER BY (i.review_status = 'pending_review') DESC, i.external_order_id"""
            ),
            {"run": job.run_id},
        ).fetchall()
        cand_rows = db.execute(
            text(
                f"""SELECT c.comparison_item_id, c.id, c.rank, c.matched_external_order_id,
                           c.matched_product_name, c.matched_image_url, c.visual_similarity,
                           c.phash_distance, c.ssim, c.color_delta_e, c.classification,
                           c.telegram_notified_at, c.decision_status, hj.custom_config
                    FROM {S}.comparison_candidates c
                    JOIN {S}.comparison_items i ON i.id = c.comparison_item_id
                    LEFT JOIN {S}.historical_jobs hj ON hj.id = c.historical_job_id
                    WHERE i.run_id = :run ORDER BY c.comparison_item_id, c.rank"""
            ),
            {"run": job.run_id},
        ).fetchall()
        by_item: dict[Any, list[dict[str, Any]]] = {}
        for r in cand_rows:
            by_item.setdefault(r[0], []).append(
                {
                    "id": str(r[1]), "rank": r[2], "order_code": r[3], "product_name": r[4],
                    "image_url": r[5], "similarity": r[6], "phash_distance": r[7],
                    "ssim": r[8], "color_delta_e": r[9], "classification": r[10],
                    "sent_to_telegram": r[11] is not None, "decision": r[12], "custom_config": r[13],
                }
            )
        links = _link_notes(db, [r[9] for r in item_rows if r[9]])
        for r in item_rows:
            items.append(
                {
                    "id": str(r[0]), "order_code": r[1], "product_name": r[2],
                    "image_url": r[3], "model_says_duplicate": bool(r[4]),
                    "review_status": r[5],
                    "selected_candidate_id": str(r[6]) if r[6] else None,
                    "reviewed_at": _iso(r[7]),
                    "custom_config": r[8],
                    "order_tag": r[10],
                    # Support may tag only an order still in Waiting that has no tag yet.
                    "taggable": (r[13] or "").upper() in SUPPORT_CLASSIFICATION_STATES
                    and (r[10] or "uncheck") == "uncheck",
                    "decision": r[11],
                    "stage": item_stage(
                        review_status=r[5], decision_status=r[11], notified_at=r[12], order_tag=r[10]
                    ),
                    "link": links.get(r[9]),
                    "candidates": by_item.get(r[0], []),
                }
            )
        out["stages"] = dict.fromkeys(STAGES, 0)
        for item in items:
            if item["stage"]:
                out["stages"][item["stage"]] += 1
        if job.status == "running":
            out["processed_count"] = len(items)
            out["duplicate_count"] = sum(1 for i in items if i["model_says_duplicate"])
            out["error_count"] = db.execute(
                text(f"SELECT count(*) FROM {S}.comparison_items WHERE run_id = :run AND processing_status = 'failed'"),
                {"run": job.run_id},
            ).scalar_one()
    return {"job": out, "items": items}


def _load_reviewable(
    db: Session,
    item_id: uuid.UUID,
    platform_id: uuid.UUID,
    allowed: tuple[str, ...] = REVIEWABLE,
) -> None:
    row = db.execute(
        text(
            f"""SELECT i.review_status,
                       EXISTS (SELECT 1 FROM {S}.comparison_candidates c
                               WHERE c.id = i.selected_candidate_id
                                 AND c.telegram_notified_at IS NOT NULL),
                       o.duplicate_check_status
                FROM {S}.comparison_items i
                LEFT JOIN public.orders o ON o.id = i.order_id
                WHERE i.id = :id AND i.platform_id = :pid AND i.processing_status = 'completed'
                FOR UPDATE OF i"""
        ),
        {"id": item_id, "pid": platform_id},
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Không tìm thấy đơn trong kết quả so sánh")
    review_status, already_sent, order_tag = row
    if review_status not in allowed:
        raise HTTPException(409, f"Đơn ở trạng thái '{review_status}', không thể duyệt")
    if already_sent:
        raise HTTPException(409, "Cặp ảnh đã được gửi Telegram, không đổi được nữa")
    if order_tag in ("duplicate", "non_duplicate"):
        raise HTTPException(
            409, "Đơn đã được chuyển trạng thái trùng lặp, chuyển lại về Chưa kiểm tra rồi mới chọn được"
        )


@router.post("/items/{item_id}/select")
def select_candidate(
    item_id: uuid.UUID,
    body: SelectBody,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _load_reviewable(db, item_id, platform_id, SELECTABLE)
    ok = db.execute(
        text(f"SELECT 1 FROM {S}.comparison_candidates WHERE id = :cid AND comparison_item_id = :iid"),
        {"cid": body.candidate_id, "iid": item_id},
    ).fetchone()
    if not ok:
        raise HTTPException(400, "Ảnh được chọn không thuộc đơn này")
    db.execute(
        text(
            f"""UPDATE {S}.comparison_items
                SET review_status = 'selected_duplicate', selected_candidate_id = :cid,
                    reviewed_at = now(), updated_at = now()
                WHERE id = :iid"""
        ),
        {"cid": body.candidate_id, "iid": item_id},
    )
    db.commit()
    return {"item_id": str(item_id), "review_status": "selected_duplicate"}


@router.post("/items/{item_id}/reject")
def reject_item(
    item_id: uuid.UUID,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _load_reviewable(db, item_id, platform_id)
    db.execute(
        text(
            f"""UPDATE {S}.comparison_items
                SET review_status = 'ai_wrong', selected_candidate_id = NULL,
                    reviewed_at = now(), updated_at = now()
                WHERE id = :iid"""
        ),
        {"iid": item_id},
    )
    db.commit()
    return {"item_id": str(item_id), "review_status": "ai_wrong"}


LINK_NOTE_PREFIX = "Link đơn trùng:"


def _link_notes(db: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The latest "Link đơn trùng" work note of each order, as the URL Support pasted."""
    if not order_ids:
        return {}
    rows = (
        db.query(OrderWorkNote.order_id, OrderWorkNote.body)
        .filter(OrderWorkNote.order_id.in_(order_ids), OrderWorkNote.body.like(f"{LINK_NOTE_PREFIX}%"))
        .order_by(OrderWorkNote.created_at.asc())
        .all()
    )
    return {order_id: body[len(LINK_NOTE_PREFIX):].strip() for order_id, body in rows}


class SendBody(BaseModel):
    target: str = Field(pattern="^(support|admin)$")
    admin_id: uuid.UUID | None = None
    include_waiting: bool = False


class TagBody(BaseModel):
    to: str = Field(pattern="^(duplicate|non_duplicate)$")


class LinkBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


def _telegram_admins(db: Session, platform_id: uuid.UUID) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.role == ROLE_ADMIN,
            User.active.is_(True),
            User.telegram_chat_id.isnot(None),
            (User.platform_id == platform_id) | (User.platform_id.is_(None)),
        )
        .order_by(User.full_name, User.username)
        .all()
    )


@router.get("/telegram-admins")
def list_telegram_admins(
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Admins linked to the Telegram bot: the accounts Support may send a lot's pairs to."""
    return {
        "admins": [
            {"id": str(a.id), "name": a.full_name or a.username, "telegram_username": a.telegram_username}
            for a in _telegram_admins(db, platform_id)
        ]
    }


@router.post("/jobs/{job_id}/send")
def send_job_pairs(
    job_id: uuid.UUID,
    body: SendBody,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Send every chosen, not-yet-sent pair of a lot to Support's own Telegram or to one Admin."""
    job = _get_job_or_404(db, job_id, platform_id)
    if job.run_id is None:
        raise HTTPException(409, "Lô này chưa có kết quả so sánh")
    if body.target == "admin":
        admin = next((a for a in _telegram_admins(db, platform_id) if a.id == body.admin_id), None)
        if admin is None:
            raise HTTPException(409, "Admin này chưa liên kết Telegram hoặc không thuộc platform")
        recipients = [admin]
    else:
        recipients = None  # every linked Support account, as before
    sent = send_lot_pairs(
        db, run_id=job.run_id, recipients=recipients, include_waiting=body.include_waiting
    )
    if sent == 0:
        raise HTTPException(409, "Không có đơn nào để gửi, hoặc không gửi được qua Telegram")
    return {"sent": sent}


@router.post("/jobs/{job_id}/tag")
def tag_job_orders(
    job_id: uuid.UUID,
    body: TagBody,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Move the lot's verified duplicates to Trùng lặp, or its non-duplicates to Không trùng lặp."""
    job = _get_job_or_404(db, job_id, platform_id)
    if job.run_id is None:
        raise HTTPException(409, "Lô này chưa có kết quả so sánh")
    target = DUPLICATE_CHECK_DUPLICATE if body.to == "duplicate" else DUPLICATE_CHECK_NON_DUPLICATE
    try:
        moved, skipped = tag_lot_orders(db, actor=user, platform_id=platform_id, run_id=job.run_id, target=target)
    except DuplicateBoardError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    if moved == 0 and not skipped:
        raise HTTPException(409, "Không có đơn nào để chuyển")
    return {"moved": moved, "skipped": skipped}


@router.post("/items/{item_id}/link")
async def save_item_link(
    item_id: uuid.UUID,
    body: LinkBody,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Write the link Support pasted into the order's work note (visible to Admin and designers)."""
    url = body.url.strip()
    if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
        raise HTTPException(422, "Link phải bắt đầu bằng http:// hoặc https://")
    row = db.execute(
        text(f"SELECT order_id FROM {S}.comparison_items WHERE id = :id AND platform_id = :pid"),
        {"id": item_id, "pid": platform_id},
    ).fetchone()
    order = db.get(Order, row[0]) if row else None
    if order is None or order.platform_id != platform_id:
        raise HTTPException(404, "Không tìm thấy đơn")
    if order.duplicate_check_status != DUPLICATE_CHECK_DUPLICATE:
        raise HTTPException(409, "Chỉ gắn link cho đơn đã chuyển sang Trùng lặp")
    await create_work_note(
        db,
        order_id=order.id,
        author=user,
        body=f"{LINK_NOTE_PREFIX} {url}",
        idempotency_key=f"dup-link:{item_id}:{uuid.uuid4().hex}",
        images=[],
    )
    return {"item_id": str(item_id), "link": url}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: uuid.UUID,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Support cancels a queued/running job. Items compared so far are kept; nothing is sent to Telegram."""
    job = db.query(SupportCompareJob).filter(SupportCompareJob.id == job_id).with_for_update().first()
    if job is None or job.platform_id != platform_id:
        raise HTTPException(404, "Không tìm thấy job")
    if job.status not in ("queued", "running"):
        raise HTTPException(409, "Job đã kết thúc, không hủy được")
    now = datetime.now(UTC)
    job.status = "failed"
    job.last_error = f"Đã hủy bởi {user.full_name or user.username}"
    job.finished_at = now
    job.notification_sent_at = now  # a cancel is not a failure to report on Telegram
    db.commit()
    return {"job_id": str(job.id), "status": job.status}


# --------------------------------------------------------------------------- image search


@router.post("/search", status_code=status.HTTP_202_ACCEPTED)
def create_search(
    file: UploadFile = File(...),
    top_k: int = 10,
    user: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not 1 <= top_k <= 30:
        raise HTTPException(400, "top_k phải từ 1 đến 30")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Ảnh quá lớn (tối đa 10 MB)")
    if not data:
        raise HTTPException(400, "Tệp rỗng")
    job = sw.create_search_job(
        db, platform_id=platform_id, user_id=user.id, filename=file.filename, image=data, top_k=top_k
    )
    db.commit()
    return {"id": str(job.id), "status": job.status}


@router.get("/search/{search_id}")
def get_search(
    search_id: uuid.UUID,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    job = db.get(SupportSearchJob, search_id)
    if job is None or job.platform_id != platform_id:
        raise HTTPException(404, "Không tìm thấy yêu cầu tìm ảnh")
    result = job.result
    if result and result.get("candidates"):
        job_ids = [c["historical_job_id"] for c in result["candidates"] if c.get("historical_job_id")]
        configs = {
            str(row[0]): row[1]
            for row in db.execute(
                text(f"SELECT id, custom_config FROM {S}.historical_jobs WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": job_ids},
            ).fetchall()
        } if job_ids else {}
        result = {
            **result,
            "candidates": [
                {**c, "custom_config": configs.get(c.get("historical_job_id") or "")} for c in result["candidates"]
            ],
        }
    return {
        "id": str(job.id),
        "status": job.status,
        "result": result,
        "error": job.last_error,
        "created_at": _iso(job.created_at),
        "finished_at": _iso(job.finished_at),
    }
