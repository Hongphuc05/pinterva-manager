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

import os
import uuid
from typing import Any, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
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
                       error_count, run_id, created_at, finished_at
                FROM {S}.comparison_jobs WHERE id = %s""",
            (job_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(404, "Không tìm thấy job")
        run_id = job[6]
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
    return {"job": _job_row(job), "items": items}


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
