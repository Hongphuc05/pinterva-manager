"""Server side of the Support compute agent (device login + job/search queue).

The VPS never runs DINO. A Support machine pairs with the web by *device login*
(``gh auth login`` style): the agent shows a short code, a signed-in Support/Admin
approves it on the web, and the agent then receives a token. The token works only
while the approving user's web page keeps sending presence heartbeats, so closing the
web or logging out stops the machine from taking (or continuing) work.

Work items are handed out with a lease (``heartbeat_at``): a job whose lease expired is
re-claimed by another machine and resumes with the orders that still have no completed
comparison item.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.db.models import (
    Order,
    Platform,
    SupportCompareCandidate,
    SupportCompareItem,
    SupportCompareJob,
    SupportCompareRun,
    SupportSearchJob,
    SupportWorkerDevice,
    User,
)
from app.application.support_compare import _unchecked_scope

logger = logging.getLogger(__name__)

SCHEMA = "support_compare_image"
PRESENCE_TTL = timedelta(seconds=90)
LEASE_TTL = timedelta(seconds=180)
PENDING_TTL = timedelta(minutes=10)
DEVICE_LIFETIME = timedelta(hours=12)
AGENT_ONLINE_TTL = timedelta(seconds=60)
MAX_PENDING_DEVICES = 50
MAX_CANDIDATES = 30
CLASSIFIER_VERSION = "rule-based-v1"
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SEARCH_KEEP = timedelta(days=7)


class WorkerAuthError(Exception):
    """The device token is unknown, revoked, expired or its user is away."""

    def __init__(self, code: str, message: str, status_code: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class WorkerStateError(Exception):
    """The requested work item is not (or no longer) leased to this device."""


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalise_user_code(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _new_user_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


# --------------------------------------------------------------------------- device login


def start_device_login(session: Session, *, machine_name: str) -> tuple[SupportWorkerDevice, str]:
    now = _now()
    session.query(SupportWorkerDevice).filter(
        SupportWorkerDevice.status == "pending", SupportWorkerDevice.expires_at < now
    ).delete(synchronize_session=False)
    pending = session.query(SupportWorkerDevice).filter(SupportWorkerDevice.status == "pending").count()
    if pending >= MAX_PENDING_DEVICES:
        raise WorkerAuthError("too_many_pending", "Có quá nhiều yêu cầu kết nối đang chờ, thử lại sau.", 429)
    device_code = secrets.token_urlsafe(32)
    device = SupportWorkerDevice(
        machine_name=(machine_name.strip() or "Máy Support")[:128],
        user_code=_new_user_code(),
        device_code_hash=_sha256(device_code),
        status="pending",
        expires_at=now + PENDING_TTL,
    )
    session.add(device)
    session.flush()
    return device, device_code


def find_pending_device(session: Session, user_code: str) -> SupportWorkerDevice | None:
    wanted = _normalise_user_code(user_code)
    if len(wanted) != 8:
        return None
    rows = (
        session.query(SupportWorkerDevice)
        .filter(SupportWorkerDevice.status == "pending", SupportWorkerDevice.expires_at > _now())
        .all()
    )
    return next((row for row in rows if _normalise_user_code(row.user_code) == wanted), None)


def approve_device(
    session: Session, *, user: User, platform_id: uuid.UUID, user_code: str
) -> SupportWorkerDevice:
    device = find_pending_device(session, user_code)
    if device is None:
        raise WorkerStateError("Mã không đúng hoặc đã hết hạn. Hãy chạy lại agent để lấy mã mới.")
    now = _now()
    device.status = "approved"
    device.user_id = user.id
    device.platform_id = platform_id
    device.approved_at = now
    device.presence_at = now
    device.expires_at = now + DEVICE_LIFETIME
    token = "sw_" + secrets.token_urlsafe(32)
    device.token_hash = _sha256(token)
    device.token_delivery = token
    session.flush()
    return device


def poll_device(session: Session, device_code: str) -> dict[str, Any]:
    device = (
        session.query(SupportWorkerDevice)
        .filter(SupportWorkerDevice.device_code_hash == _sha256(device_code))
        .with_for_update()
        .first()
    )
    if device is None:
        return {"status": "expired"}
    if device.status == "pending":
        return {"status": "pending" if device.expires_at > _now() else "expired"}
    if device.status == "revoked":
        return {"status": "denied"}
    token = device.token_delivery
    if token is None:
        # Already collected once: the agent must start a new login.
        return {"status": "expired"}
    device.token_delivery = None
    session.flush()
    return {"status": "approved", "token": token, "device_id": str(device.id)}


def authenticate_device(session: Session, token: str | None) -> SupportWorkerDevice:
    if not token:
        raise WorkerAuthError("no_token", "Thiếu token của máy.", 401)
    device = (
        session.query(SupportWorkerDevice)
        .filter(SupportWorkerDevice.token_hash == _sha256(token))
        .with_for_update()
        .first()
    )
    now = _now()
    if device is None or device.status != "approved":
        raise WorkerAuthError("revoked", "Máy đã bị thu hồi quyền. Hãy kết nối lại.", 401)
    if device.expires_at <= now:
        device.status = "revoked"
        session.flush()
        raise WorkerAuthError("expired", "Phiên của máy đã hết hạn. Hãy kết nối lại.", 401)
    user = session.get(User, device.user_id) if device.user_id else None
    if user is None or not user.active:
        raise WorkerAuthError("user_inactive", "Tài khoản đã cho phép máy này không còn hoạt động.", 401)
    if device.presence_at is None or device.presence_at < now - PRESENCE_TTL:
        raise WorkerAuthError(
            "presence_lost", "Chưa có Support nào đăng nhập và mở web để cho phép máy này chạy.", 403
        )
    device.last_seen_at = now
    return device


def touch_presence(session: Session, user_id: uuid.UUID) -> list[SupportWorkerDevice]:
    now = _now()
    devices = (
        session.query(SupportWorkerDevice)
        .filter(
            SupportWorkerDevice.user_id == user_id,
            SupportWorkerDevice.status == "approved",
            SupportWorkerDevice.expires_at > now,
        )
        .all()
    )
    for device in devices:
        device.presence_at = now
    session.flush()
    return devices


def revoke_device(session: Session, device: SupportWorkerDevice) -> None:
    device.status = "revoked"
    device.token_delivery = None
    device.busy_with = None
    session.flush()


def revoke_user_devices(session: Session, user_id: uuid.UUID) -> int:
    devices = (
        session.query(SupportWorkerDevice)
        .filter(SupportWorkerDevice.user_id == user_id, SupportWorkerDevice.status == "approved")
        .all()
    )
    for device in devices:
        revoke_device(session, device)
    return len(devices)


def device_state(device: SupportWorkerDevice, now: datetime | None = None) -> str:
    """paused (no user on the web) / busy / idle / offline (agent stopped polling)."""
    now = now or _now()
    if device.status != "approved" or device.expires_at <= now:
        return "revoked"
    if device.presence_at is None or device.presence_at < now - PRESENCE_TTL:
        return "paused"
    if device.last_seen_at is None or device.last_seen_at < now - AGENT_ONLINE_TTL:
        return "offline"
    return "busy" if device.busy_with else "idle"


# --------------------------------------------------------------------------- claiming


def _normalise_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("/"):
        return urljoin("https://printerval.com", value)
    return value


def first_image_url(thumbnail_url: Any, product_image_urls: Any) -> str | None:
    """Same primary-preview contract as the review and the pool."""
    primary = _normalise_url(thumbnail_url)
    if primary:
        return primary
    if isinstance(product_image_urls, list):
        for item in product_image_urls:
            normalised = _normalise_url(item.get("url") if isinstance(item, dict) else item)
            if normalised:
                return normalised
    return None


def pending_job_orders(session: Session, platform_id: uuid.UUID) -> list[dict[str, Any]]:
    """Orders a job still has to compare: Support's unchecked scope without a completed item."""
    from sqlalchemy import exists

    never_compared = ~exists().where(
        SupportCompareItem.order_id == Order.id, SupportCompareItem.processing_status == "completed"
    )
    rows = (
        session.query(Order)
        .filter(*_unchecked_scope(platform_id), never_compared)
        .order_by(Order.created_at.asc(), Order.id.asc())
        .all()
    )
    orders: list[dict[str, Any]] = []
    for order in rows:
        url = first_image_url(order.thumbnail_url, order.product_image_urls)
        if not url:
            logger.warning("skip order %s: no preview URL", order.external_order_id)
            continue
        orders.append(
            {
                "order_id": str(order.id),
                "external_order_id": order.external_order_id,
                "product_name": order.product_name,
                "image_url": url,
            }
        )
    return orders


def _claimable(query, model, now: datetime):
    return query.filter(
        (model.status == "queued")
        | ((model.status == "running") & ((model.heartbeat_at.is_(None)) | (model.heartbeat_at < now - LEASE_TTL)))
    )


def claim_work(
    session: Session, device: SupportWorkerDevice, *, model_version: str, embedding_dim: int
) -> dict[str, Any]:
    now = _now()
    search = (
        _claimable(session.query(SupportSearchJob), SupportSearchJob, now)
        .filter(SupportSearchJob.platform_id == device.platform_id)
        .order_by(SupportSearchJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if search is not None:
        search.status = "running"
        search.device_id = device.id
        search.claimed_at = now
        search.heartbeat_at = now
        device.busy_with = f"search:{search.id}"
        session.flush()
        return {"kind": "search", "search": {"id": str(search.id), "top_k": search.top_k}}

    job = (
        _claimable(session.query(SupportCompareJob), SupportCompareJob, now)
        .filter(SupportCompareJob.platform_id == device.platform_id)
        .order_by(SupportCompareJob.created_at.asc(), SupportCompareJob.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        device.busy_with = None
        return {"kind": "none"}

    orders = pending_job_orders(session, job.platform_id)
    job.status = "running"
    job.worker_id = device.machine_name
    job.device_id = device.id
    job.claimed_at = now
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.finished_at = None
    job.notification_sent_at = None
    job.last_error = None
    job.model_version = model_version
    run = session.get(SupportCompareRun, job.run_id) if job.run_id else None
    if run is None:
        run = SupportCompareRun(
            id=uuid.uuid4(),
            source_kind=job.source_kind,
            platform_id=job.platform_id,
            model_version=model_version,
            embedding_dim=embedding_dim,
            classifier_version=CLASSIFIER_VERSION,
            run_status="running",
            baseline_count=0,
            requested_count=job.requested_count,
            promote_new_images=True,
            started_at=now,
        )
        session.add(run)
        session.flush()
        job.run_id = run.id
    device.busy_with = f"job:{job.id}"
    session.flush()
    return {
        "kind": "job",
        "job": {
            "id": str(job.id),
            "run_id": str(run.id),
            "requested_count": job.requested_count,
            "orders": orders,
        },
    }


def _leased_job(session: Session, device: SupportWorkerDevice, job_id: uuid.UUID) -> SupportCompareJob:
    job = session.query(SupportCompareJob).filter(SupportCompareJob.id == job_id).with_for_update().first()
    if job is None or job.status != "running" or job.device_id != device.id:
        raise WorkerStateError("Job không còn được giao cho máy này (đã hủy hoặc máy khác nhận tiếp).")
    return job


def heartbeat_job(session: Session, device: SupportWorkerDevice, job_id: uuid.UUID) -> None:
    job = _leased_job(session, device, job_id)
    job.heartbeat_at = _now()


def _leased_search(session: Session, device: SupportWorkerDevice, search_id: uuid.UUID) -> SupportSearchJob:
    job = session.query(SupportSearchJob).filter(SupportSearchJob.id == search_id).with_for_update().first()
    if job is None or job.status != "running" or job.device_id != device.id:
        raise WorkerStateError("Yêu cầu tìm ảnh không còn được giao cho máy này.")
    return job


# --------------------------------------------------------------------------- pool download


def pool_page(
    session: Session, *, model_version: str, embedding_dim: int, after: str | None, limit: int
) -> dict[str, Any]:
    after_ts: datetime | None = None
    after_id: uuid.UUID | None = None
    if after:
        stamp, _, asset = after.partition("|")
        after_ts = datetime.fromisoformat(stamp)
        after_id = uuid.UUID(asset)
    rows = session.execute(
        text(
            f"""
            SELECT e.asset_id, e.embedding, e.created_at, e.phash, e.color_l, e.color_a, e.color_b,
                   a.url, hist.job_id, hist.external_order_id, hist.product_name
            FROM {SCHEMA}.image_embeddings e
            JOIN {SCHEMA}.image_assets a ON a.id = e.asset_id
            LEFT JOIN LATERAL (
                SELECT hj.id AS job_id, hj.external_order_id, hj.product_name
                FROM {SCHEMA}.job_images ji
                JOIN {SCHEMA}.historical_jobs hj ON hj.id = ji.job_id
                WHERE ji.asset_id = e.asset_id
                ORDER BY ji.is_primary DESC, ji.position ASC, hj.id ASC
                LIMIT 1
            ) hist ON TRUE
            WHERE e.model_version = :mv AND e.embedding_dim = :dim
              AND (CAST(:after_ts AS timestamptz) IS NULL
                   OR (e.created_at, e.asset_id) > (CAST(:after_ts AS timestamptz), CAST(:after_id AS uuid)))
            ORDER BY e.created_at, e.asset_id
            LIMIT :limit
            """
        ),
        {
            "mv": model_version,
            "dim": embedding_dim,
            "after_ts": after_ts,
            "after_id": str(after_id) if after_id else None,
            "limit": limit,
        },
    ).fetchall()
    items = []
    for row in rows:
        raw = bytes(row[1])
        if len(raw) != embedding_dim * 4:
            continue
        items.append(
            {
                "asset_id": str(row[0]),
                "embedding": base64.b64encode(raw).decode("ascii"),
                "phash": row[3],
                "lab": [row[4], row[5], row[6]],
                "image_url": row[7],
                "job_id": str(row[8]) if row[8] else None,
                "external_order_id": row[9],
                "product_name": row[10],
            }
        )
    next_cursor = f"{rows[-1][2].isoformat()}|{rows[-1][0]}" if len(rows) == limit else None
    return {"items": items, "next_cursor": next_cursor}


# --------------------------------------------------------------------------- results


def submit_items(
    session: Session, device: SupportWorkerDevice, job_id: uuid.UUID, items: list[dict[str, Any]]
) -> dict[str, int]:
    job = _leased_job(session, device, job_id)
    run = session.get(SupportCompareRun, job.run_id)
    now = _now()
    stored = failed = skipped = 0
    for payload in items:
        order = session.get(Order, payload["order_id"])
        if order is None or order.platform_id != job.platform_id:
            skipped += 1
            continue
        image_url = first_image_url(order.thumbnail_url, order.product_image_urls)
        if not image_url:
            skipped += 1
            continue
        sha = _sha256(image_url)
        item = (
            session.query(SupportCompareItem)
            .filter(
                SupportCompareItem.run_id == run.id,
                SupportCompareItem.order_id == order.id,
                SupportCompareItem.image_url_sha256 == sha,
                SupportCompareItem.model_version == run.model_version,
            )
            .first()
        )
        if item is not None and item.processing_status == "completed":
            skipped += 1
            continue
        if item is None:
            item = SupportCompareItem(
                id=uuid.uuid4(),
                run_id=run.id,
                platform_id=order.platform_id,
                order_id=order.id,
                external_order_id=order.external_order_id,
                product_name=(order.product_name or None) and order.product_name[:512],
                source_state=order.state,
                source_printerval_status=order.printerval_status,
                source_order_version=order.version,
                image_url=image_url,
                image_url_sha256=sha,
                model_version=run.model_version,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
        item.updated_at = now
        if payload["status"] == "failed":
            item.processing_status = "failed"
            item.last_error = (payload.get("error") or "Lỗi không rõ")[:2000]
            failed += 1
            session.flush()
            continue

        embedding = base64.b64decode(payload["embedding_b64"])
        if len(embedding) != run.embedding_dim * 4:
            raise ValueError(f"embedding length {len(embedding)} does not match dim {run.embedding_dim}")
        item.embedding = embedding
        item.embedding_dim = run.embedding_dim
        item.phash = payload["phash"]
        item.color_l, item.color_a, item.color_b = payload["lab"]
        item.classification = payload["classification"]
        item.is_duplicate = bool(payload["is_duplicate"])
        item.review_status = "pending_review" if item.is_duplicate else "no_match"
        item.processing_status = "completed"
        item.last_error = None
        session.flush()
        for cand in payload["candidates"][:MAX_CANDIDATES]:
            existing = (
                session.query(SupportCompareCandidate)
                .filter(
                    SupportCompareCandidate.comparison_item_id == item.id,
                    SupportCompareCandidate.historical_asset_id == cand["historical_asset_id"],
                    SupportCompareCandidate.classifier_version == CLASSIFIER_VERSION,
                )
                .first()
            )
            row = existing or SupportCompareCandidate(
                id=uuid.uuid4(),
                comparison_item_id=item.id,
                historical_asset_id=cand["historical_asset_id"],
                classifier_version=CLASSIFIER_VERSION,
                created_at=now,
            )
            row.historical_job_id = cand.get("historical_job_id")
            row.matched_external_order_id = cand.get("matched_external_order_id")
            row.matched_product_name = cand.get("matched_product_name")
            row.matched_image_url = cand["matched_image_url"]
            row.rank = cand["rank"]
            row.visual_similarity = cand["visual_similarity"]
            row.phash_distance = cand.get("phash_distance")
            row.ssim = cand.get("ssim")
            row.color_delta_e = cand.get("color_delta_e")
            row.classification = cand["classification"]
            row.confidence = cand["confidence"]
            row.reasons = cand.get("reasons") or []
            row.decision_status = "pending"
            if existing is None:
                session.add(row)
        stored += 1
    job.heartbeat_at = now
    session.flush()
    return {"stored": stored, "failed": failed, "skipped": skipped}


def _promote_item(session: Session, item: SupportCompareItem, order: Order, team_outsource: str) -> None:
    """Add a compared order to the pool (historical job + asset + embedding)."""
    source_system = "tacahu_live"
    url = item.image_url
    url_hash = _sha256(url)
    status = (order.printerval_status or order.state or "waiting")[:16]
    payload_hash = hashlib.sha256(f"{order.external_order_id}:{url}".encode()).hexdigest()
    config = json.dumps(order.custom_config) if order.custom_config else None
    job_id = session.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.historical_jobs
                (id, source_system, source_job_id, external_order_id, status, team_outsource,
                 job_type, order_id, product_name, preview_url, preview_missing,
                 source_payload_hash, ingest_source, custom_config, custom_config_synced_at)
            VALUES (:id, :sys, :sjid, :ext, :status, :team, 'all', :oid, :pname, :url, false,
                    :phash, 'live_waiting', CAST(:cfg AS jsonb), now())
            ON CONFLICT (source_system, source_job_id) DO UPDATE SET
                external_order_id = EXCLUDED.external_order_id, status = EXCLUDED.status,
                team_outsource = EXCLUDED.team_outsource, order_id = EXCLUDED.order_id,
                product_name = EXCLUDED.product_name, preview_url = EXCLUDED.preview_url,
                preview_missing = false, source_payload_hash = EXCLUDED.source_payload_hash,
                ingest_source = EXCLUDED.ingest_source, custom_config = EXCLUDED.custom_config,
                custom_config_synced_at = now(), last_seen_at = now()
            RETURNING id
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "sys": source_system,
            "sjid": str(order.id),
            "ext": order.external_order_id,
            "status": status,
            "team": team_outsource[:128],
            "oid": str(order.id),
            "pname": (order.product_name or "")[:512],
            "url": url,
            "phash": payload_hash,
            "cfg": config,
        },
    ).scalar_one()
    asset_id = session.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.image_assets
                (id, source_system, url_sha256, raw_url, url, fetch_status, content_sha256, width, height)
            VALUES (:id, :sys, :hash, :url, :url, 'embedded', NULL, NULL, NULL)
            ON CONFLICT (source_system, url_sha256) DO UPDATE SET
                url = EXCLUDED.url, fetch_status = 'embedded', last_error = NULL, last_seen_at = now()
            RETURNING id
            """
        ),
        {"id": str(uuid.uuid4()), "sys": source_system, "hash": url_hash, "url": url},
    ).scalar_one()
    session.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.job_images (id, job_id, asset_id, role, position, is_primary)
            VALUES (:id, :job, :asset, 'preview', 0, true)
            ON CONFLICT (job_id, role, position) DO UPDATE SET asset_id = EXCLUDED.asset_id, is_primary = true
            """
        ),
        {"id": str(uuid.uuid4()), "job": str(job_id), "asset": str(asset_id)},
    )
    session.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.image_embeddings
                (asset_id, model_version, embedding, embedding_dim, phash, color_l, color_a, color_b)
            VALUES (:asset, :mv, :emb, :dim, :phash, :l, :a, :b)
            ON CONFLICT (asset_id, model_version) DO UPDATE SET
                embedding = EXCLUDED.embedding, embedding_dim = EXCLUDED.embedding_dim,
                phash = EXCLUDED.phash, color_l = EXCLUDED.color_l, color_a = EXCLUDED.color_a,
                color_b = EXCLUDED.color_b, created_at = now()
            """
        ),
        {
            "asset": str(asset_id),
            "mv": item.model_version,
            "emb": item.embedding,
            "dim": item.embedding_dim,
            "phash": item.phash,
            "l": item.color_l,
            "a": item.color_a,
            "b": item.color_b,
        },
    )
    item.pool_promoted_at = _now()
    item.pool_promotion_error = None


def promote_run_items(session: Session, run: SupportCompareRun) -> int:
    """Add every compared, not yet promoted order of the run to the pool (whole batch at once,
    after comparing, so orders of one batch never match each other)."""
    platform = session.get(Platform, run.platform_id) if run.platform_id else None
    team = (platform.team_outsource if platform and platform.team_outsource else None) or "unknown"
    items = (
        session.query(SupportCompareItem)
        .filter(
            SupportCompareItem.run_id == run.id,
            SupportCompareItem.processing_status == "completed",
            SupportCompareItem.pool_promoted_at.is_(None),
            SupportCompareItem.embedding.is_not(None),
        )
        .all()
    )
    promoted = 0
    for item in items:
        order = session.get(Order, item.order_id)
        if order is None:
            continue
        try:
            with session.begin_nested():
                _promote_item(session, item, order, team)
            promoted += 1
        except Exception as exc:  # one broken row must not block the batch
            logger.exception("pool promotion failed for order %s", item.external_order_id)
            item.pool_promotion_error = f"{type(exc).__name__}: {exc}"[:2000]
    session.flush()
    return promoted


def _run_counts(session: Session, run_id: uuid.UUID) -> tuple[int, int, int]:
    def count(*criteria) -> int:
        return session.query(SupportCompareItem).filter(SupportCompareItem.run_id == run_id, *criteria).count()

    return (
        count(SupportCompareItem.processing_status == "completed"),
        count(SupportCompareItem.is_duplicate.is_(True), SupportCompareItem.processing_status == "completed"),
        count(SupportCompareItem.processing_status == "failed"),
    )


def complete_job(
    session: Session, device: SupportWorkerDevice, job_id: uuid.UUID, *, baseline_count: int
) -> dict[str, Any]:
    job = _leased_job(session, device, job_id)
    run = session.get(SupportCompareRun, job.run_id)
    promote_run_items(session, run)
    processed, duplicates, errors = _run_counts(session, run.id)
    now = _now()
    run.run_status = "completed"
    run.baseline_count = baseline_count
    run.processed_count, run.duplicate_count, run.error_count = processed, duplicates, errors
    run.finished_at = now
    summary = {
        "run_id": str(run.id),
        "run_status": "completed",
        "source_kind": job.source_kind,
        "model_version": run.model_version,
        "embedding_dim": run.embedding_dim,
        "baseline_count": baseline_count,
        "requested_count": job.requested_count,
        "processed_count": processed,
        "duplicate_count": duplicates,
        "error_count": errors,
    }
    job.status = "completed"
    job.processed_count, job.duplicate_count, job.error_count = processed, duplicates, errors
    job.summary = summary
    job.finished_at = now
    job.heartbeat_at = now
    device.busy_with = None
    session.flush()
    return summary


def fail_job(session: Session, device: SupportWorkerDevice, job_id: uuid.UUID, *, error: str) -> None:
    job = _leased_job(session, device, job_id)
    now = _now()
    job.status = "failed"
    job.last_error = error[:2000]
    job.summary = {"error_type": "AgentError"}
    job.finished_at = now
    job.heartbeat_at = now
    run = session.get(SupportCompareRun, job.run_id) if job.run_id else None
    if run is not None:
        run.run_status = "failed"
        run.last_error = error[:2000]
        run.finished_at = now
    device.busy_with = None
    session.flush()


# --------------------------------------------------------------------------- search


def create_search_job(
    session: Session, *, platform_id: uuid.UUID, user_id: uuid.UUID, filename: str | None, image: bytes, top_k: int
) -> SupportSearchJob:
    cutoff = _now() - SEARCH_KEEP
    session.query(SupportSearchJob).filter(SupportSearchJob.created_at < cutoff).delete(
        synchronize_session=False
    )
    job = SupportSearchJob(
        platform_id=platform_id,
        requested_by_id=user_id,
        filename=(filename or "")[:255] or None,
        image=image,
        top_k=top_k,
    )
    session.add(job)
    session.flush()
    return job


def search_image(session: Session, device: SupportWorkerDevice, search_id: uuid.UUID) -> bytes:
    job = _leased_search(session, device, search_id)
    job.heartbeat_at = _now()
    if not job.image:
        raise WorkerStateError("Ảnh của yêu cầu tìm không còn.")
    return bytes(job.image)


def heartbeat_search(session: Session, device: SupportWorkerDevice, search_id: uuid.UUID) -> None:
    _leased_search(session, device, search_id).heartbeat_at = _now()


def complete_search(
    session: Session, device: SupportWorkerDevice, search_id: uuid.UUID, result: dict[str, Any]
) -> None:
    job = _leased_search(session, device, search_id)
    now = _now()
    job.status = "completed"
    job.result = result
    job.image = None
    job.finished_at = now
    job.heartbeat_at = now
    device.busy_with = None
    session.flush()


def fail_search(session: Session, device: SupportWorkerDevice, search_id: uuid.UUID, error: str) -> None:
    job = _leased_search(session, device, search_id)
    now = _now()
    job.status = "failed"
    job.last_error = error[:2000]
    job.image = None
    job.finished_at = now
    job.heartbeat_at = now
    device.busy_with = None
    session.flush()
