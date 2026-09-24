"""API for the Support compute agent and the web page that lets it run.

Agent side (device token, no user session): device login, claiming work, downloading the
image pool, reporting results. Web side (Support/Admin session): approve a machine, keep it
allowed with presence heartbeats, revoke it.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import SupportWorkerDevice, User
from app.api.deps import get_current_platform_id, get_db, require_any_role
from app.application import support_worker as sw
from app.config import get_settings
from app.domain.access import ROLE_ADMIN, ROLE_SUPPORT

router = APIRouter(prefix="/support-worker")

_web_user = require_any_role(ROLE_ADMIN, ROLE_SUPPORT)


# --------------------------------------------------------------------------- helpers


def _device_out(device: SupportWorkerDevice, users: dict[uuid.UUID, str] | None = None) -> dict:
    return {
        "id": str(device.id),
        "machine_name": device.machine_name,
        "state": sw.device_state(device),
        "user_id": str(device.user_id) if device.user_id else None,
        "user_name": (users or {}).get(device.user_id) if device.user_id else None,
        "busy_with": device.busy_with,
        "approved_at": device.approved_at.isoformat() if device.approved_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "presence_at": device.presence_at.isoformat() if device.presence_at else None,
        "expires_at": device.expires_at.isoformat(),
    }


def get_worker_device(request: Request, db: Session = Depends(get_db)) -> SupportWorkerDevice:
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    try:
        return sw.authenticate_device(db, token)
    except sw.WorkerAuthError as exc:
        db.commit()  # keep a revoke/expiry decided while authenticating
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


WorkerDevice = Annotated[SupportWorkerDevice, Depends(get_worker_device)]


def _state_error(exc: sw.WorkerStateError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": "lease_lost", "message": str(exc)})


# --------------------------------------------------------------------------- device login (agent)


class DeviceStartIn(BaseModel):
    machine_name: str = Field(default="", max_length=128)


class DevicePollIn(BaseModel):
    device_code: str = Field(min_length=10, max_length=200)


@router.post("/device/start")
def device_start(payload: DeviceStartIn, db: Session = Depends(get_db)):
    try:
        device, device_code = sw.start_device_login(db, machine_name=payload.machine_name)
    except sw.WorkerAuthError as exc:
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    db.commit()
    base = (get_settings().public_web_url or "").rstrip("/")
    return {
        "device_code": device_code,
        "user_code": device.user_code,
        "verification_uri": f"{base}/support-queue" if base else None,
        "interval": 3,
        "expires_in": int(sw.PENDING_TTL.total_seconds()),
    }


@router.post("/device/poll")
def device_poll(payload: DevicePollIn, db: Session = Depends(get_db)):
    result = sw.poll_device(db, payload.device_code)
    db.commit()
    return result


# --------------------------------------------------------------------------- web side


class ApproveIn(BaseModel):
    user_code: str = Field(min_length=8, max_length=16)


@router.post("/devices/lookup")
def device_lookup(
    payload: ApproveIn, user: User = Depends(_web_user), db: Session = Depends(get_db)
):
    """Show which machine a code belongs to before the user allows it."""
    device = sw.find_pending_device(db, payload.user_code)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mã không đúng hoặc đã hết hạn.")
    return {"machine_name": device.machine_name, "user_code": device.user_code}


@router.post("/devices/approve")
def device_approve(
    payload: ApproveIn,
    user: User = Depends(_web_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    try:
        device = sw.approve_device(db, user=user, platform_id=platform_id, user_code=payload.user_code)
    except sw.WorkerStateError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    return _device_out(device, {user.id: user.full_name or user.username})


@router.get("/devices")
def devices_list(
    user: User = Depends(_web_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    devices = (
        db.query(SupportWorkerDevice)
        .filter(
            SupportWorkerDevice.platform_id == platform_id,
            SupportWorkerDevice.status == "approved",
            SupportWorkerDevice.expires_at > sw._now(),
        )
        .order_by(SupportWorkerDevice.approved_at.desc())
        .all()
    )
    names = {
        u.id: (u.full_name or u.username)
        for u in db.query(User).filter(User.id.in_([d.user_id for d in devices if d.user_id])).all()
    }
    return {"devices": [_device_out(d, names) for d in devices]}


@router.post("/presence")
def presence(user: User = Depends(_web_user), db: Session = Depends(get_db)):
    """Heartbeat of an open web page: keeps this user's machines allowed to compute."""
    devices = sw.touch_presence(db, user.id)
    db.commit()
    return {"devices": [_device_out(d, {user.id: user.full_name or user.username}) for d in devices]}


@router.post("/devices/{device_id}/revoke")
def device_revoke(
    device_id: uuid.UUID,
    user: User = Depends(_web_user),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    device = db.get(SupportWorkerDevice, device_id)
    if device is None or device.platform_id != platform_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy máy")
    if device.user_id != user.id and user.role != ROLE_ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ người đã cho phép hoặc Admin mới dừng được máy này")
    sw.revoke_device(db, device)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- claiming (agent)


class ClaimIn(BaseModel):
    model_version: str = Field(min_length=1, max_length=128)
    embedding_dim: int = Field(gt=0, le=4096)


@router.post("/claim")
def claim(payload: ClaimIn, device: WorkerDevice, db: Session = Depends(get_db)):
    result = sw.claim_work(
        db, device, model_version=payload.model_version, embedding_dim=payload.embedding_dim
    )
    db.commit()
    return result


@router.get("/pool")
def pool(
    device: WorkerDevice,
    model_version: str,
    embedding_dim: int,
    after: str | None = None,
    limit: int = 2000,
    db: Session = Depends(get_db),
):
    try:
        page = sw.pool_page(
            db,
            model_version=model_version,
            embedding_dim=embedding_dim,
            after=after,
            limit=max(1, min(limit, 5000)),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Con trỏ pool không hợp lệ") from exc
    db.commit()  # persist last_seen_at
    return page


class CandidateIn(BaseModel):
    historical_job_id: uuid.UUID | None = None
    historical_asset_id: uuid.UUID
    matched_external_order_id: str | None = Field(default=None, max_length=128)
    matched_product_name: str | None = Field(default=None, max_length=512)
    matched_image_url: str = Field(max_length=4000)
    rank: int = Field(ge=1, le=100)
    visual_similarity: float = Field(ge=-1.0, le=1.0)
    phash_distance: int | None = Field(default=None, ge=0, le=4096)
    ssim: float | None = Field(default=None, ge=-1.0, le=1.0)
    color_delta_e: float | None = Field(default=None, ge=0)
    classification: str = Field(max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=20)


class ItemIn(BaseModel):
    order_id: uuid.UUID
    status: Literal["completed", "failed"]
    error: str | None = Field(default=None, max_length=2000)
    embedding_b64: str | None = None
    phash: str | None = Field(default=None, max_length=128)
    lab: list[float] | None = Field(default=None, min_length=3, max_length=3)
    classification: str | None = Field(default=None, max_length=32)
    is_duplicate: bool = False
    candidates: list[CandidateIn] = Field(default_factory=list, max_length=sw.MAX_CANDIDATES)


class ItemsIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=50)


@router.post("/jobs/{job_id}/heartbeat")
def job_heartbeat(job_id: uuid.UUID, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        sw.heartbeat_job(db, device, job_id)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/items")
def job_items(job_id: uuid.UUID, payload: ItemsIn, device: WorkerDevice, db: Session = Depends(get_db)):
    items = []
    for item in payload.items:
        data = item.model_dump()
        if item.status == "completed":
            try:
                base64.b64decode(item.embedding_b64 or "", validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(422, "embedding không hợp lệ") from exc
            if not (item.phash and item.lab and item.classification):
                raise HTTPException(422, "Thiếu phash/lab/classification")
        items.append(data)
    try:
        result = sw.submit_items(db, device, job_id, items)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return result


class CompleteIn(BaseModel):
    baseline_count: int = Field(ge=0)


class FailIn(BaseModel):
    error: str = Field(max_length=4000)


@router.post("/jobs/{job_id}/complete")
def job_complete(job_id: uuid.UUID, payload: CompleteIn, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        summary = sw.complete_job(db, device, job_id, baseline_count=payload.baseline_count)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return summary


@router.post("/jobs/{job_id}/fail")
def job_fail(job_id: uuid.UUID, payload: FailIn, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        sw.fail_job(db, device, job_id, error=payload.error)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- search (agent)


@router.get("/search/{search_id}/image")
def search_image(search_id: uuid.UUID, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        data = sw.search_image(db, device, search_id)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return Response(content=data, media_type="application/octet-stream")


@router.post("/search/{search_id}/heartbeat")
def search_heartbeat(search_id: uuid.UUID, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        sw.heartbeat_search(db, device, search_id)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return {"ok": True}


class SearchResultIn(BaseModel):
    result: dict


@router.post("/search/{search_id}/result")
def search_result(
    search_id: uuid.UUID, payload: SearchResultIn, device: WorkerDevice, db: Session = Depends(get_db)
):
    try:
        sw.complete_search(db, device, search_id, payload.result)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return {"ok": True}


@router.post("/search/{search_id}/fail")
def search_fail(search_id: uuid.UUID, payload: FailIn, device: WorkerDevice, db: Session = Depends(get_db)):
    try:
        sw.fail_search(db, device, search_id, payload.error)
    except sw.WorkerStateError as exc:
        raise _state_error(exc) from exc
    db.commit()
    return {"ok": True}
