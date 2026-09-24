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

from app.adapters.db.models import SupportCompareJob, SupportSearchJob, User
from app.api.deps import get_current_platform_id, get_db, require_any_role
from app.application import support_review_access as access_svc
from app.application import support_worker as sw
from app.domain.access import ROLE_SUPPORT

S = "support_compare_image"
# States in which the reviewer may still change the decision. Once the pair was sent to
# Telegram (telegram_notified_at set) the choice is frozen.
REVIEWABLE = ("pending_review", "ai_wrong", "selected_duplicate")
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
    return {"jobs": [_job_row(r) for r in rows]}


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
                           i.review_status, i.selected_candidate_id, i.reviewed_at, o.custom_config
                    FROM {S}.comparison_items i
                    LEFT JOIN public.orders o ON o.id = i.order_id
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
        for r in item_rows:
            items.append(
                {
                    "id": str(r[0]), "order_code": r[1], "product_name": r[2],
                    "image_url": r[3], "model_says_duplicate": bool(r[4]),
                    "review_status": r[5],
                    "selected_candidate_id": str(r[6]) if r[6] else None,
                    "reviewed_at": _iso(r[7]),
                    "custom_config": r[8],
                    "candidates": by_item.get(r[0], []),
                }
            )
        if job.status == "running":
            out["processed_count"] = len(items)
            out["duplicate_count"] = sum(1 for i in items if i["model_says_duplicate"])
            out["error_count"] = db.execute(
                text(f"SELECT count(*) FROM {S}.comparison_items WHERE run_id = :run AND processing_status = 'failed'"),
                {"run": job.run_id},
            ).scalar_one()
    return {"job": out, "items": items}


def _load_reviewable(db: Session, item_id: uuid.UUID, platform_id: uuid.UUID) -> None:
    row = db.execute(
        text(
            f"""SELECT i.review_status,
                       EXISTS (SELECT 1 FROM {S}.comparison_candidates c
                               WHERE c.id = i.selected_candidate_id
                                 AND c.telegram_notified_at IS NOT NULL)
                FROM {S}.comparison_items i
                WHERE i.id = :id AND i.platform_id = :pid AND i.processing_status = 'completed'
                FOR UPDATE"""
        ),
        {"id": item_id, "pid": platform_id},
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Không tìm thấy đơn trong kết quả so sánh")
    review_status, already_sent = row
    if review_status not in REVIEWABLE:
        raise HTTPException(409, f"Đơn ở trạng thái '{review_status}', không thể duyệt")
    if already_sent:
        raise HTTPException(409, "Cặp ảnh đã được gửi Telegram, không đổi được nữa")


@router.post("/items/{item_id}/select")
def select_candidate(
    item_id: uuid.UUID,
    body: SelectBody,
    _u: User = Depends(require_unlock),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _load_reviewable(db, item_id, platform_id)
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
