"""Comparison primitives shared by the Support agent and the tests.

Loads DINOv2 directly (no HOG fallback: a fallback vector must never be compared with the
DINOv2 pool) and scores one image against the historical pool: cosine similarity, pHash,
colour ΔE and SSIM, then the rule-based classifier. Pure functions, no database access: the
agent gets the pool over HTTPS and posts the results back (see ``agent.py``).
"""

from __future__ import annotations

import io
import logging
import urllib.request
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .classifier import CLASS_KHONG_TRUNG, CLASS_TRUNG, classify
from .embedding import DinoV2Embedder
from .signals import (
    color_delta_e_from_lab,
    compute_phash,
    mean_lab,
    phash_distance_from_hex,
    phash_max_distance,
    ssim_score,
)

logger = logging.getLogger("dup_compare.core")

IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_EMBEDDER_CACHE: dict[str, DinoV2Embedder] = {}


@dataclass(frozen=True)
class HistoricalImage:
    asset_id: uuid.UUID
    job_id: uuid.UUID | None
    external_order_id: str | None
    product_name: str | None
    image_url: str
    embedding: np.ndarray
    embedding_dim: int
    model_version: str
    phash: str
    color_lab: tuple[float, float, float]


@dataclass(frozen=True)
class CandidateResult:
    historical: HistoricalImage
    rank: int
    visual_similarity: float
    phash_distance: int
    ssim: float | None
    color_delta_e: float
    classification: str
    confidence: float
    reasons: list[str]


def fetch_image(url: str, *, timeout: float = 30.0, max_bytes: int = 25_000_000) -> Image.Image:
    request = urllib.request.Request(url, headers={"User-Agent": IMAGE_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError(f"image is larger than {max_bytes} bytes")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"image is larger than {max_bytes} bytes")
            chunks.append(chunk)
    return Image.open(io.BytesIO(b"".join(chunks))).convert("RGB")


class ImageCache:
    """Small bounded cache for old top-K images used by SSIM."""

    def __init__(self, max_size: int = 2048):
        self.max_size = max_size
        self._items: OrderedDict[str, Image.Image | None] = OrderedDict()

    def get(self, url: str, *, timeout: float) -> Image.Image | None:
        if url in self._items:
            value = self._items.pop(url)
            self._items[url] = value
            return value
        try:
            value = fetch_image(url, timeout=timeout)
        except Exception as exc:  # one broken historical URL must not stop a run
            logger.warning("cannot fetch historical image %s: %s", url, exc)
            value = None
        self._items[url] = value
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)
        return value


def _pick_overall(candidates: Sequence[CandidateResult]) -> tuple[str, bool]:
    """Use the highest-scoring historical image as the decision anchor."""
    if not candidates:
        return CLASS_KHONG_TRUNG, False
    best = min(candidates, key=lambda item: item.rank)
    is_duplicate = best.classification == CLASS_TRUNG
    return (CLASS_TRUNG if is_duplicate else CLASS_KHONG_TRUNG), is_duplicate


def _candidate_indexes(
    pool: Sequence[HistoricalImage],
    pool_matrix: np.ndarray,
    embedding: np.ndarray,
    *,
    external_order_id: str,
    top_k: int,
    exclude_self: bool,
) -> list[tuple[int, float]]:
    if not pool:
        return []
    allowed = np.ones(len(pool), dtype=bool)
    if exclude_self:
        allowed = np.array(
            [row.external_order_id != external_order_id for row in pool], dtype=bool
        )
    indexes = np.flatnonzero(allowed)
    if indexes.size == 0:
        return []
    scores = pool_matrix[indexes] @ embedding
    selected = np.argsort(-scores)[:top_k]
    return [(int(indexes[position]), float(np.clip(scores[position], -1.0, 1.0))) for position in selected]


def compare_image_to_pool(
    image: Image.Image,
    embedding: np.ndarray,
    *,
    external_order_id: str,
    pool: Sequence[HistoricalImage],
    pool_matrix: np.ndarray,
    top_k: int,
    old_image_cache: ImageCache,
    fetch_timeout: float,
    exclude_self: bool,
) -> tuple[str, bool, str, tuple[float, float, float], list[CandidateResult]]:
    new_phash = str(compute_phash(image))
    new_lab = mean_lab(image)
    candidate_results: list[CandidateResult] = []

    for rank, (pool_index, visual_similarity) in enumerate(
        _candidate_indexes(
            pool,
            pool_matrix,
            embedding,
            external_order_id=external_order_id,
            top_k=top_k,
            exclude_self=exclude_self,
        ),
        start=1,
    ):
        historical = pool[pool_index]
        try:
            p_dist = phash_distance_from_hex(new_phash, historical.phash)
        except Exception:
            p_dist = phash_max_distance()
        try:
            delta_e = color_delta_e_from_lab(new_lab, historical.color_lab)
        except Exception:
            delta_e = 0.0
        old_image = old_image_cache.get(historical.image_url, timeout=fetch_timeout)
        ssim_value = ssim_score(image, old_image) if old_image is not None else None
        result = classify(
            visual_similarity=visual_similarity,
            phash_dist=p_dist,
            color_de=delta_e,
            ssim_value=ssim_value,
        )
        candidate_results.append(
            CandidateResult(
                historical=historical,
                rank=rank,
                visual_similarity=round(visual_similarity, 6),
                phash_distance=p_dist,
                ssim=None if ssim_value is None else round(ssim_value, 6),
                color_delta_e=round(delta_e, 6),
                classification=result.classification,
                confidence=round(result.confidence, 6),
                reasons=result.reasons,
            )
        )

    overall, is_duplicate = _pick_overall(candidate_results)
    return overall, is_duplicate, new_phash, new_lab, candidate_results


def get_cached_embedder(model_name: str) -> DinoV2Embedder:
    """Keep the model resident while the local worker processes multiple jobs."""
    embedder = _EMBEDDER_CACHE.get(model_name)
    if embedder is None:
        logger.info("loading Hugging Face model %s", model_name)
        embedder = DinoV2Embedder(model_name)
        _EMBEDDER_CACHE[model_name] = embedder
    return embedder
