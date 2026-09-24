"""Search the image pool with a picture uploaded from this machine (read-only).

The picture is embedded with the same DINOv2 model and scored against the Postgres pool exactly
like a job order (visual similarity, pHash, SSIM), so the verdict matches what the worker would say.
The pool (~85k vectors, ~260 MB) is loaded on the first search and reused; it is refreshed every
30 minutes or on request so orders added by recent jobs show up.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
from typing import Any

import numpy as np
import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from .postgres_compare import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MODEL_NAME,
    PostgresComparisonRepository,
    _get_embedder,
    _ImageCache,
    _psycopg_url,
    compare_image_to_pool,
)
from .review import _local_only

logger = logging.getLogger("dup_compare.search")

router = APIRouter(prefix="/review/search")

MAX_UPLOAD_BYTES = 25_000_000
POOL_TTL_SECONDS = 1800
FETCH_TIMEOUT = 15.0

_pool_lock = threading.Lock()
_infer_lock = threading.Lock()
_pool: dict[str, Any] = {"rows": None, "matrix": None, "loaded_at": 0.0}
_image_cache = _ImageCache()


def _settings() -> tuple[str, str, int]:
    name = os.environ.get("EMBEDDING_MODEL_NAME", DEFAULT_MODEL_NAME)
    return name, os.environ.get("MODEL_VERSION") or name, int(os.environ.get("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM))


def _get_pool(force: bool = False) -> tuple[list, np.ndarray]:
    with _pool_lock:
        stale = time.time() - _pool["loaded_at"] > POOL_TTL_SECONDS
        if _pool["rows"] is None or force or stale:
            url = os.environ.get("DATABASE_URL", "")
            if not url:
                raise HTTPException(503, "Thiếu biến môi trường DATABASE_URL")
            _, version, dim = _settings()
            with psycopg.connect(_psycopg_url(url)) as conn:
                rows = PostgresComparisonRepository(conn).list_historical_images(model_version=version, embedding_dim=dim)
            if not rows:
                raise HTTPException(503, f"Pool chưa có embedding nào cho model {version}")
            _pool.update(rows=rows, matrix=np.stack([r.embedding for r in rows]).astype(np.float32), loaded_at=time.time())
            logger.info("pool loaded: %s images", len(rows))
        return _pool["rows"], _pool["matrix"]


def _configs(job_ids: list) -> dict[str, dict | None]:
    if not job_ids:
        return {}
    with psycopg.connect(_psycopg_url(os.environ["DATABASE_URL"])) as conn:
        rows = conn.execute(
            "SELECT id, custom_config FROM support_compare_image.historical_jobs WHERE id = ANY(%s)", (job_ids,)
        ).fetchall()
    return {str(r[0]): r[1] for r in rows}


@router.post("", dependencies=[Depends(_local_only)])
def search_by_image(file: UploadFile = File(...), top_k: int = 10, refresh: bool = False) -> dict[str, Any]:
    started = time.time()
    if not 1 <= top_k <= 30:
        raise HTTPException(400, "top_k phải từ 1 đến 30")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Ảnh quá lớn (tối đa 25 MB)")
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(415, "Tệp không phải ảnh hợp lệ") from exc

    rows, matrix = _get_pool(refresh)
    name, version, _ = _settings()
    with _infer_lock:
        embedding = np.asarray(_get_embedder(name).encode_batch([image])[0], dtype=np.float32)
    overall, is_duplicate, _phash, _lab, candidates = compare_image_to_pool(
        image, embedding, external_order_id="", pool=rows, pool_matrix=matrix, top_k=top_k,
        old_image_cache=_image_cache, fetch_timeout=FETCH_TIMEOUT, exclude_self=False,
    )
    configs = _configs([c.historical.job_id for c in candidates if c.historical.job_id])
    return {
        "verdict": overall,
        "is_duplicate": is_duplicate,
        "pool_count": len(rows),
        "model_version": version,
        "elapsed_ms": round((time.time() - started) * 1000),
        "candidates": [
            {
                "rank": c.rank,
                "order_code": c.historical.external_order_id,
                "product_name": c.historical.product_name,
                "image_url": c.historical.image_url,
                "similarity": c.visual_similarity,
                "phash_distance": c.phash_distance,
                "ssim": c.ssim,
                "color_delta_e": c.color_delta_e,
                "classification": c.classification,
                "reasons": c.reasons,
                "custom_config": configs.get(str(c.historical.job_id)),
            }
            for c in candidates
        ],
    }
