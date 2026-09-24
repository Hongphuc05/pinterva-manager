"""
FastAPI service — module standalone để test model khuyến nghị trước khi
tích hợp vào pipeline production đầy đủ.

Endpoint:
- POST /compare            : so 1-1, ad-hoc, upload trực tiếp 2 ảnh.
- /review/*                : duyệt kết quả job và tìm ảnh trong pool (review.py, search.py).

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

from .review import router as review_router
from .search import router as search_router
from .classifier import classify
from .config import (
    MODEL_CONFIG,
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


app.include_router(review_router)  # before the static mount, which catches every path
app.include_router(search_router)

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


# Legacy 1-1 compare tool at /index.html.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
