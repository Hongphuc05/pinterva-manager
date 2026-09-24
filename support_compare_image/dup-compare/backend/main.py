"""
FastAPI service — module standalone để test model khuyến nghị trước khi
tích hợp vào pipeline production đầy đủ.

Có 2 nhóm endpoint:
- POST /compare            : so 1-1, ad-hoc, upload trực tiếp 2 ảnh (bản cũ, giữ nguyên).
- /admin/*                 : luồng "pool tăng dần" theo folder data/old, data/new
                             + SQLite (ingest, scan tuần tự, xem pool, xem ảnh, reset).

Chạy: uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import db, scan
from .review import router as review_router
from .classifier import classify
from .config import (
    DB_PATH,
    MODEL_CONFIG,
    NEW_IMAGES_DIR,
    OLD_IMAGES_DIR,
    THRESHOLDS,
    TOP_K_CANDIDATES,
)
from .embedding import get_embedder
from .signals import color_delta_e, phash_distance, phash_max_distance, ssim_score

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dup_compare.main")

app = FastAPI(title="Duplicate Design Compare (MVP)", version=MODEL_CONFIG.processing_version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _load_image(upload: UploadFile) -> Image.Image:
    data = upload.file.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


@app.get("/health")
def health():
    embedder = get_embedder()
    return {
        "status": "ok",
        "embedding_backend": embedder.name,
        "model_version": MODEL_CONFIG.model_version,
        "processing_version": MODEL_CONFIG.processing_version,
        "old_images_dir": str(OLD_IMAGES_DIR),
        "new_images_dir": str(NEW_IMAGES_DIR),
        "db_path": str(DB_PATH),
    }


@app.get("/config")
def get_config():
    return {
        "thresholds": THRESHOLDS.__dict__,
        "embedding_model_name": MODEL_CONFIG.embedding_model_name,
        "top_k_candidates": TOP_K_CANDIDATES,
    }


# ---------------------------------------------------------------------------
# So 1-1, ad-hoc (giữ nguyên bản gốc, không đụng DB/pool)
# ---------------------------------------------------------------------------
@app.post("/compare")
def compare(old_image: UploadFile = File(...), new_image: UploadFile = File(...)):
    t0 = time.time()
    embedder = get_embedder()

    img_old = _load_image(old_image)
    img_new = _load_image(new_image)

    emb_old = embedder.encode(img_old)
    emb_new = embedder.encode(img_new)
    visual_similarity = embedder.cosine_similarity(emb_old, emb_new)

    p_dist = phash_distance(img_old, img_new)
    ssim_value = ssim_score(img_old, img_new)
    color_de = color_delta_e(img_old, img_new)

    result = classify(
        visual_similarity=visual_similarity,
        phash_dist=p_dist,
        color_de=color_de,
        ssim_value=ssim_value,
    )

    elapsed_ms = round((time.time() - t0) * 1000, 1)

    return {
        "is_duplicate": result.is_duplicate,
        "classification": result.classification,
        "confidence": round(result.confidence, 4),
        "signals": {
            "visual_similarity": round(visual_similarity, 4),
            "phash_distance": p_dist,
            "phash_max_distance": phash_max_distance(),
            "ssim": round(ssim_value, 4),
            "color_delta_e": round(color_de, 2),
            "ocr_similarity": None,
        },
        "reasons": result.reasons,
        "meta": {
            "embedding_backend": embedder.name,
            "model_version": MODEL_CONFIG.model_version,
            "processing_version": MODEL_CONFIG.processing_version,
            "elapsed_ms": elapsed_ms,
        },
    }


# ---------------------------------------------------------------------------
# Luồng "pool tăng dần": data/old, data/new + SQLite
# ---------------------------------------------------------------------------
@app.get("/admin/pool")
def admin_pool():
    embedder = get_embedder()
    with db.connect(DB_PATH) as conn:
        stats = db.pool_stats(conn)
        other = db.count_other_model_versions(conn, embedder.name)
    return {
        "pool_stats": stats,
        "current_model_version": embedder.name,
        "images_with_other_model_version": other,
    }


@app.post("/admin/ingest-old")
def admin_ingest_old():
    """Quét data/old, encode + lưu những ảnh chưa có trong DB. Idempotent —
    gọi lại nhiều lần không tính trùng."""
    t0 = time.time()
    embedder = get_embedder()
    with db.connect(DB_PATH) as conn:
        result = scan.ingest_folder(conn, OLD_IMAGES_DIR, source="old", embedder=embedder)
    return {
        "added": result.added,
        "skipped": result.skipped,
        "added_count": len(result.added),
        "skipped_count": len(result.skipped),
        "embedding_backend": embedder.name,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


@app.post("/admin/scan-new")
def admin_scan_new():
    """Quét data/new TUẦN TỰ theo tên file. Mỗi ảnh so với toàn bộ pool hiện
    có (old + new đã xử lý trước đó trong lượt này), gắn tag, rồi add vào
    pool cho ảnh kế tiếp."""
    t0 = time.time()
    embedder = get_embedder()
    with db.connect(DB_PATH) as conn:
        results = scan.scan_new_sequential(
            conn, NEW_IMAGES_DIR, embedder=embedder, top_k=TOP_K_CANDIDATES
        )
    return {
        "results": results,
        "processed_count": sum(1 for r in results if not r.get("skipped")),
        "skipped_count": sum(1 for r in results if r.get("skipped")),
        "embedding_backend": embedder.name,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


@app.post("/admin/reset")
def admin_reset():
    """XÓA TOÀN BỘ DB (không đụng file ảnh gốc trong data/old, data/new).
    Dùng khi muốn test lại từ đầu."""
    db.reset_db(DB_PATH)
    return {"status": "reset_done", "db_path": str(DB_PATH)}


@app.get("/admin/image/{image_id}")
def admin_get_image(image_id: int):
    """Trả về file ảnh theo id trong DB — để frontend hiển thị thumbnail."""
    with db.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT file_path FROM images WHERE id = ?", (image_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="image_id không tồn tại")
    if row[0].startswith(("http://", "https://")):  # đơn crawl: ảnh nằm ở link asset
        return RedirectResponse(row[0])
    return FileResponse(row[0])


# Serve frontend tĩnh tại "/" (index.html = so 1-1, scan.html = pool tăng dần).
app.include_router(review_router)  # before the static mount, which catches every path

# The review UI (React + Vite, see review-ui/) is served at "/". Docker builds it into the
# image (REVIEW_UI_DIST); otherwise run `npm ci && npm run build` inside review-ui/.
_UI_DIST = Path(os.environ.get("REVIEW_UI_DIST") or Path(__file__).resolve().parent.parent / "review-ui" / "dist")
if (_UI_DIST / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=_UI_DIST / "assets"), name="review-assets")

    @app.get("/", include_in_schema=False)
    @app.get("/review.html", include_in_schema=False)
    def review_ui():
        return FileResponse(_UI_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def review_ui_missing():
        return PlainTextResponse(
            "Chưa build giao diện duyệt. Chạy: cd review-ui && npm ci && npm run build "
            "(hoặc dùng docker compose up -d --build).",
            status_code=503,
        )


# Legacy tools (1-1 compare at /index.html, pool scan at /scan.html).
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
