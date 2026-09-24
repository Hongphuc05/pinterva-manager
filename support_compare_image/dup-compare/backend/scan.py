"""
Orchestration cho luồng "pool tăng dần":

  - ingest_folder(): quét 1 thư mục, encode + lưu DB những ảnh CHƯA có
    (idempotent — chạy lại không tính trùng lần 2).
  - scan_new_sequential(): quét thư mục `new/` THEO THỨ TỰ TÊN FILE, mỗi
    ảnh so với toàn bộ pool hiện có (old + new đã xử lý trước đó trong
    cùng lượt chạy), gắn tag, rồi add luôn vào pool cho ảnh kế tiếp.

Brute-force bằng nhân ma trận numpy trong RAM: ~100k ảnh vẫn dưới 1s/đợt.
Lên cỡ vài triệu ảnh (RAM không đủ) mới cần vector search có index
(pgvector/HNSW) — điểm cắm thay thế nằm ở `db.get_pool()`.
"""
from __future__ import annotations

import io
import logging
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
from PIL import Image

from . import db
from .classifier import CLASS_TRUNG, classify
from .config import MODEL_CONFIG, TOP_K_CANDIDATES
from .embedding import VisualEmbedder
from .signals import (
    color_delta_e_from_lab,
    compute_phash,
    mean_lab,
    phash_distance_from_hex,
    ssim_score,
)

logger = logging.getLogger("dup_compare.scan")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
CLASSIFIER_VERSION = "rule-based-v1"


def _open_image(file_path: str) -> Image.Image:
    """file_path là path local hoặc link asset (đơn crawl không giữ ảnh trên đĩa)."""
    if file_path.startswith(("http://", "https://")):
        with urllib.request.urlopen(file_path, timeout=30) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGB")
    return Image.open(file_path).convert("RGB")


def _list_images(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    return sorted(
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


@dataclass
class IngestResult:
    added: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def ingest_folder(
    conn, folder: Path, source: str, embedder: VisualEmbedder
) -> IngestResult:
    result = IngestResult()
    for path in _list_images(folder):
        file_path = str(path.resolve())
        if db.image_exists(conn, file_path):
            result.skipped.append(path.name)
            continue
        img = Image.open(path).convert("RGB")
        emb = embedder.encode(img)
        phash = str(compute_phash(img))
        lab = mean_lab(img)
        db.insert_image(
            conn,
            file_path=file_path,
            file_name=path.name,
            source=source,
            embedding=emb,
            phash=phash,
            color_lab=lab,
            model_version=embedder.name,
            processing_version=MODEL_CONFIG.processing_version,
        )
        result.added.append(path.name)
    return result


def _pick_overall(match_classifications: List[str]) -> tuple:
    """Chỉ 2 tag: TRUNG nếu có ít nhất 1 candidate TRUNG, ngược lại KHONG_TRUNG."""
    is_dup = CLASS_TRUNG in match_classifications
    return (CLASS_TRUNG if is_dup else "KHONG_TRUNG"), is_dup


def scan_new_sequential(
    conn, folder: Path, embedder: VisualEmbedder, top_k: int = TOP_K_CANDIDATES
) -> List[dict]:
    results = []

    # Cảnh báo sớm nếu DB có ảnh từ model_version khác — những ảnh đó sẽ bị
    # loại khỏi pool so sánh (không cùng không gian vector), không âm thầm
    # bỏ qua mà không ai biết.
    other_model_count = db.count_other_model_versions(conn, embedder.name)
    if other_model_count:
        logger.warning(
            "Có %d ảnh trong DB thuộc model_version khác '%s' — bị loại khỏi "
            "pool so sánh lần này. Cần reindex nếu vừa đổi model.",
            other_model_count,
            embedder.name,
        )

    # Load pool 1 lần thành ma trận (100k x 768 float32 ~ 300MB) rồi nhân ma
    # trận, thay vì đọc lại DB + loop Python cho từng ảnh mới. Ảnh mới xử lý
    # xong được append vào `pool` để ảnh kế tiếp trong cùng đợt so với nó.
    pool = db.get_pool(conn, embedder.name)
    pool_mat = np.stack([r.embedding for r in pool]) if pool else None

    for path in _list_images(folder):
        file_path = str(path.resolve())
        if db.image_exists(conn, file_path):
            results.append(
                {"file_name": path.name, "skipped": True, "reason": "đã xử lý trước đó"}
            )
            continue

        img_new = Image.open(path).convert("RGB")
        emb_new = embedder.encode(img_new)
        phash_new = str(compute_phash(img_new))
        lab_new = mean_lab(img_new)

        if not pool:
            # Pool rỗng (chưa ingest ảnh cũ nào) -> chắc chắn UNIQUE.
            candidates_detail = []
            overall, is_dup = "KHONG_TRUNG", False
        else:
            # Embedding đã L2-normalize -> dot product = cosine.
            n_mat = 0 if pool_mat is None else len(pool_mat)
            sims = np.concatenate([
                pool_mat @ emb_new if n_mat else np.empty(0, dtype=np.float32),
                np.array([r.embedding @ emb_new for r in pool[n_mat:]], dtype=np.float32),
            ])
            top_idx = np.argsort(-sims)[:top_k]
            top = [(float(np.clip(sims[i], -1.0, 1.0)), pool[i]) for i in top_idx]

            candidates_detail = []
            for sim, row in top:
                p_dist = phash_distance_from_hex(phash_new, row.phash)
                try:
                    ssim_v = ssim_score(img_new, _open_image(row.file_path))
                except Exception as exc:  # link chết / file bị xóa: bỏ qua SSIM, không làm chết cả đợt
                    logger.warning("Không mở được ảnh cũ %s (%s) -> bỏ qua SSIM", row.file_path, exc)
                    ssim_v = None
                de = color_delta_e_from_lab(lab_new, row.color_lab)

                cls_result = classify(
                    visual_similarity=sim,
                    phash_dist=p_dist,
                    color_de=de,
                    ssim_value=ssim_v,
                )
                candidates_detail.append(
                    {
                        "matched_image_id": row.id,
                        "matched_file_name": row.file_name,
                        "matched_source": row.source,
                        "visual_similarity": round(sim, 4),
                        "phash_distance": p_dist,
                        "ssim": None if ssim_v is None else round(ssim_v, 4),
                        "color_delta_e": round(de, 2),
                        "classification": cls_result.classification,
                        "confidence": round(cls_result.confidence, 4),
                    }
                )

            overall, is_dup = _pick_overall([c["classification"] for c in candidates_detail])

        new_image_id = db.insert_image(
            conn,
            file_path=file_path,
            file_name=path.name,
            source="new",
            embedding=emb_new,
            phash=phash_new,
            color_lab=lab_new,
            model_version=embedder.name,
            processing_version=MODEL_CONFIG.processing_version,
            classification=overall,
            is_duplicate=is_dup,
        )
        pool.append(
            db.ImageRow(
                id=new_image_id, file_path=file_path, file_name=path.name, source="new",
                embedding=emb_new.astype(np.float32), phash=phash_new, color_lab=lab_new,
                classification=overall, is_duplicate=is_dup, model_version=embedder.name,
            )
        )

        for c in candidates_detail:
            db.insert_match(
                conn,
                new_image_id=new_image_id,
                matched_image_id=c["matched_image_id"],
                visual_similarity=c["visual_similarity"],
                phash_distance=c["phash_distance"],
                ssim=-1.0 if c["ssim"] is None else c["ssim"],  # -1 = không tải được ảnh cũ
                color_delta_e=c["color_delta_e"],
                classification=c["classification"],
                confidence=c["confidence"],
                classifier_version=CLASSIFIER_VERSION,
            )

        results.append(
            {
                "image_id": new_image_id,
                "file_name": path.name,
                "skipped": False,
                "classification": overall,
                "is_duplicate": is_dup,
                "matches": candidates_detail,
            }
        )

    return results
