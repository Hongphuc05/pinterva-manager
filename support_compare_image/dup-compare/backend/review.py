"""Localhost review of a Support comparison job.

Reads the items/candidates the local worker wrote for a job and records the
reviewer's choice on ``comparison_items``:

* select   -> ``selected_duplicate``: the VPS sends the (original, selected) pair to
              Support on Telegram, where Xác nhận / Từ chối makes the final decision;
* reject   -> ``ai_wrong``: the model was wrong; the order stays in Chưa kiểm tra
              until Support runs /handle.

Only ``support_compare_image`` rows are written; orders are never touched here.
Every item, candidate and message carries the order code (``external_order_id``).
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

S = "support_compare_image"
# States in which the reviewer may still change the decision. Once the pair was
# sent to Telegram (telegram_notified_at set) the choice is frozen.
REVIEWABLE = ("pending_review", "ai_wrong", "selected_duplicate")

router = APIRouter(prefix="/review")


def _local_only(request: Request) -> None:
    """The review API writes to the production DB: accept only same-origin
    requests to a loopback host (blocks other web pages and DNS rebinding)."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "Chỉ dùng qua localhost")
    origin = request.headers.get("origin")
    if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
        raise HTTPException(403, "Origin không hợp lệ")


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not url:
        raise HTTPException(503, "Thiếu biến môi trường DATABASE_URL (nạp .env.local-worker)")
    return psycopg.connect(url)


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


@router.get("/img", dependencies=[Depends(_local_only)])
def proxy_image(url: str) -> Response:
    """Serve a product image through the local server: sends the same headers as the worker
    (no Referer, browser User-Agent) so hotlink protection on third-party CDNs does not break it."""
    data, content_type = _fetch_image(url)
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=86400"})


class SelectBody(BaseModel):
    candidate_id: uuid.UUID


def _job_row(row: tuple) -> dict[str, Any]:
    keys = ("id", "status", "requested_count", "processed_count", "duplicate_count",
            "error_count", "run_id", "created_at", "finished_at")
    out = dict(zip(keys, row))
    for key in ("id", "run_id"):
        out[key] = str(out[key]) if out[key] else None
    for key in ("created_at", "finished_at"):
        out[key] = out[key].isoformat() if out[key] else None
    return out


@router.get("/jobs", dependencies=[Depends(_local_only)])
def list_jobs(limit: int = 15) -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT id, status, requested_count, processed_count, duplicate_count,
                       error_count, run_id, created_at, finished_at
                FROM {S}.comparison_jobs ORDER BY created_at DESC LIMIT %s""",
            (max(1, min(limit, 50)),),
        ).fetchall()
    return {"jobs": [_job_row(r) for r in rows]}


@router.get("/jobs/{job_id}", dependencies=[Depends(_local_only)])
def get_job(job_id: uuid.UUID) -> dict[str, Any]:
    with _connect() as conn:
        job = conn.execute(
            f"""SELECT id, status, requested_count, processed_count, duplicate_count,
                       error_count, run_id, created_at, finished_at,
                       platform_id, source_kind, claimed_at
                FROM {S}.comparison_jobs WHERE id = %s""",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Không tìm thấy job")
        out = _job_row(job[:9])
        run_id = job[6]
        if run_id is None and job[1] == "running" and job[11] is not None:
            # The worker only writes run_id/counters on completion: find its run and show live progress.
            run = conn.execute(
                f"""SELECT id FROM {S}.comparison_runs
                    WHERE platform_id = %s AND source_kind = %s AND started_at >= %s
                    ORDER BY started_at DESC LIMIT 1""",
                (job[9], job[10], job[11]),
            ).fetchone()
            run_id = run[0] if run else None
        items: list[dict[str, Any]] = []
        if run_id:
            item_rows = conn.execute(
                f"""SELECT id, external_order_id, product_name, image_url, is_duplicate,
                           review_status, selected_candidate_id, reviewed_at
                    FROM {S}.comparison_items
                    WHERE run_id = %s AND processing_status = 'completed'
                    ORDER BY (review_status = 'pending_review') DESC, external_order_id""",
                (run_id,),
            ).fetchall()
            cand_rows = conn.execute(
                f"""SELECT c.comparison_item_id, c.id, c.rank, c.matched_external_order_id,
                           c.matched_product_name, c.matched_image_url, c.visual_similarity,
                           c.phash_distance, c.ssim, c.color_delta_e, c.classification,
                           c.telegram_notified_at, c.decision_status
                    FROM {S}.comparison_candidates c
                    JOIN {S}.comparison_items i ON i.id = c.comparison_item_id
                    WHERE i.run_id = %s ORDER BY c.comparison_item_id, c.rank""",
                (run_id,),
            ).fetchall()
            by_item: dict[Any, list[dict[str, Any]]] = {}
            for r in cand_rows:
                by_item.setdefault(r[0], []).append({
                    "id": str(r[1]), "rank": r[2], "order_code": r[3], "product_name": r[4],
                    "image_url": r[5], "similarity": r[6], "phash_distance": r[7],
                    "ssim": r[8], "color_delta_e": r[9], "classification": r[10],
                    "sent_to_telegram": r[11] is not None, "decision": r[12],
                })
            for r in item_rows:
                items.append({
                    "id": str(r[0]), "order_code": r[1], "product_name": r[2],
                    "image_url": r[3], "model_says_duplicate": bool(r[4]),
                    "review_status": r[5],
                    "selected_candidate_id": str(r[6]) if r[6] else None,
                    "reviewed_at": r[7].isoformat() if r[7] else None,
                    "candidates": by_item.get(r[0], []),
                })
            if job[1] == "running":
                out["processed_count"] = len(items)
                out["duplicate_count"] = sum(1 for i in items if i["model_says_duplicate"])
                out["error_count"] = conn.execute(
                    f"SELECT count(*) FROM {S}.comparison_items WHERE run_id = %s AND processing_status = 'failed'",
                    (run_id,),
                ).fetchone()[0]
    return {"job": out, "items": items}


def _load_reviewable(conn: psycopg.Connection, item_id: uuid.UUID) -> tuple:
    row = conn.execute(
        f"""SELECT i.review_status,
                   EXISTS (SELECT 1 FROM {S}.comparison_candidates c
                           WHERE c.id = i.selected_candidate_id
                             AND c.telegram_notified_at IS NOT NULL)
            FROM {S}.comparison_items i
            WHERE i.id = %s AND i.processing_status = 'completed'
            FOR UPDATE""",
        (item_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Không tìm thấy đơn trong kết quả so sánh")
    status, already_sent = row
    if status not in REVIEWABLE:
        raise HTTPException(409, f"Đơn ở trạng thái '{status}', không thể duyệt")
    if already_sent:
        raise HTTPException(409, "Cặp ảnh đã được gửi Telegram, không đổi được nữa")
    return row


@router.post("/items/{item_id}/select", dependencies=[Depends(_local_only)])
def select_candidate(item_id: uuid.UUID, body: SelectBody) -> dict[str, Any]:
    with _connect() as conn:
        _load_reviewable(conn, item_id)
        ok = conn.execute(
            f"SELECT 1 FROM {S}.comparison_candidates WHERE id = %s AND comparison_item_id = %s",
            (body.candidate_id, item_id),
        ).fetchone()
        if not ok:
            raise HTTPException(400, "Ảnh được chọn không thuộc đơn này")
        conn.execute(
            f"""UPDATE {S}.comparison_items
                SET review_status = 'selected_duplicate', selected_candidate_id = %s,
                    reviewed_at = now(), updated_at = now()
                WHERE id = %s""",
            (body.candidate_id, item_id),
        )
    return {"item_id": str(item_id), "review_status": "selected_duplicate"}


@router.post("/items/{item_id}/reject", dependencies=[Depends(_local_only)])
def reject_item(item_id: uuid.UUID) -> dict[str, Any]:
    with _connect() as conn:
        _load_reviewable(conn, item_id)
        conn.execute(
            f"""UPDATE {S}.comparison_items
                SET review_status = 'ai_wrong', selected_candidate_id = NULL,
                    reviewed_at = now(), updated_at = now()
                WHERE id = %s""",
            (item_id,),
        )
    return {"item_id": str(item_id), "review_status": "ai_wrong"}
