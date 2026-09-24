"""PostgreSQL-backed duplicate comparison for Tacahu orders.

The original MVP scanner reads ``data/old`` and ``data/new`` and persists a
SQLite pool.  This module keeps the embedding/classifier code but replaces that
manual boundary with the production PostgreSQL database:

* historical vectors come from ``support_compare_image.image_embeddings``;
* test/live inputs come from ``public.orders``;
* comparison runs, inputs and candidates are persisted in the comparison
  tables created by migration ``0003_comparison_runs``.

The comparator deliberately loads DINOv2 directly.  The old SQLite code can
fall back to HOG for an offline demo, but a fallback vector must never be
compared with the DINOv2 historical pool.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import sys
import urllib.request
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import numpy as np
import psycopg
from PIL import Image
from psycopg.types.json import Jsonb

from .classifier import CLASS_KHONG_TRUNG, CLASS_TRUNG, classify
from .config import TOP_K_CANDIDATES
from .embedding import DinoV2Embedder
from .signals import (
    color_delta_e_from_lab,
    compute_phash,
    mean_lab,
    phash_distance_from_hex,
    phash_max_distance,
    ssim_score,
)

logger = logging.getLogger("dup_compare.postgres")

COMPARISON_SCHEMA = "support_compare_image"
DEFAULT_MODEL_NAME = "facebook/dinov2-base"
DEFAULT_EMBEDDING_DIM = 768
CLASSIFIER_VERSION = "rule-based-v1"
IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_EMBEDDER_CACHE: dict[str, DinoV2Embedder] = {}


@dataclass(frozen=True)
class SourceOrder:
    order_id: uuid.UUID
    platform_id: uuid.UUID
    external_order_id: str
    product_name: str | None
    state: str | None
    printerval_status: str | None
    version: int | None
    image_url: str
    custom_config: dict | None = None


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


def _as_uuid(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


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


def _first_image_url(thumbnail_url: Any, product_image_urls: Any) -> str | None:
    """Select the same primary-preview contract for review and waiting tests."""
    primary = _normalise_url(thumbnail_url)
    if primary:
        return primary
    if isinstance(product_image_urls, list):
        for item in product_image_urls:
            candidate = item.get("url") if isinstance(item, dict) else item
            normalised = _normalise_url(candidate)
            if normalised:
                return normalised
    return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def _decode_embedding(raw: bytes | memoryview, dimension: int) -> np.ndarray:
    vector = np.frombuffer(bytes(raw), dtype="<f4")
    if vector.ndim != 1 or vector.size != dimension:
        raise ValueError(
            f"embedding dimension mismatch: expected {dimension}, got {vector.size}"
        )
    return vector.astype(np.float32, copy=True)


def _fetch_image(url: str, *, timeout: float = 30.0, max_bytes: int = 25_000_000) -> Image.Image:
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


class _ImageCache:
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
            value = _fetch_image(url, timeout=timeout)
        except Exception as exc:  # one broken historical URL must not stop a run
            logger.warning("cannot fetch historical image %s: %s", url, exc)
            value = None
        self._items[url] = value
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)
        return value


class PostgresComparisonRepository:
    """Small SQL repository kept separate from the embedding orchestration."""

    def __init__(self, connection: psycopg.Connection):
        self.connection = connection

    def list_source_orders(
        self,
        *,
        source_kind: str,
        model_version: str | None = None,
        limit: int | None,
        platform_id: uuid.UUID | None = None,
        order_ids: Sequence[uuid.UUID] = (),
    ) -> list[SourceOrder]:
        if source_kind not in {"review", "waiting", "support_unchecked", "manual"}:
            raise ValueError(f"unsupported source_kind: {source_kind}")
        if source_kind == "manual" and not order_ids:
            raise ValueError("manual source requires at least one --order-id")

        clauses: list[str] = []
        params: list[Any] = []
        if source_kind == "review":
            clauses.append(
                "(LOWER(COALESCE(o.printerval_status, '')) = 'review' "
                "OR o.state = 'QC_PENDING')"
            )
        elif source_kind in {"waiting", "support_unchecked"}:
            clauses.extend(
                [
                    "COALESCE(o.duplicate_check_status, 'uncheck') = 'uncheck'",
                ]
            )
            if source_kind == "support_unchecked":
                # Recurring Support queue: internal state only, matching what
                # Support sees on the web (a stale printerval_status mirror on a
                # QC_PENDING/DONE order must not pull it back into the queue).
                clauses.append(
                    "(UPPER(COALESCE(o.state, '')) IN "
                    "('OPEN', 'WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', "
                    "'IN_PROGRESS', 'ASSIGNED', 'DOING'))"
                )
                clauses.append("COALESCE(o.work_domain, 'standard') <> 'duplicate'")
            else:
                clauses.append(
                    "(UPPER(COALESCE(o.state, '')) IN "
                    "('OPEN', 'WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING') "
                    "OR LOWER(COALESCE(o.printerval_status, '')) = 'waiting')"
                )

            if model_version and source_kind == "waiting":
                # A scheduler tick may see the same Waiting order repeatedly.
                # Only a successfully promoted item is terminal; failed or
                # interrupted work remains retryable on the next tick.
                clauses.append(
                    f"NOT EXISTS ("
                    f"SELECT 1 FROM {COMPARISON_SCHEMA}.comparison_items ci "
                    f"JOIN {COMPARISON_SCHEMA}.comparison_runs cr ON cr.id = ci.run_id "
                    "WHERE ci.order_id = o.id "
                    "AND cr.source_kind = 'waiting' "
                    "AND ci.model_version = %s "
                    "AND ci.processing_status = 'completed' "
                    "AND ci.pool_promoted_at IS NOT NULL)"
                )
                params.append(model_version)
            elif source_kind == "support_unchecked":
                # Each order is compared once per batch flow: an order with any
                # completed comparison is handled by the localhost review,
                # the Telegram confirmation or Support's /handle, never re-queued.
                # Failed items stay eligible so they are retried.
                clauses.append(
                    f"NOT EXISTS ("
                    f"SELECT 1 FROM {COMPARISON_SCHEMA}.comparison_items ci "
                    "WHERE ci.order_id = o.id AND ci.processing_status = 'completed')"
                )
        if platform_id is not None:
            clauses.append("o.platform_id = %s")
            params.append(platform_id)
        if order_ids:
            clauses.append("o.id = ANY(%s)")
            params.append(list(order_ids))

        query = f"""
            SELECT o.id, o.platform_id, o.external_order_id, o.product_name,
                   o.state, o.printerval_status, o.version,
                   o.thumbnail_url, o.product_image_urls, o.custom_config
            FROM public.orders o
            WHERE {' AND '.join(clauses) if clauses else 'TRUE'}
            ORDER BY o.created_at ASC, o.id ASC
        """
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)

        rows = self.connection.execute(query, params).fetchall()
        result: list[SourceOrder] = []
        for row in rows:
            if not row[1]:
                logger.warning("skip order %s: no platform_id", row[2])
                continue
            image_url = _first_image_url(row[7], row[8])
            if not image_url:
                logger.warning("skip order %s: no preview URL", row[2])
                continue
            result.append(
                SourceOrder(
                    order_id=_as_uuid(row[0]),
                    platform_id=_as_uuid(row[1]),
                    external_order_id=str(row[2]),
                    product_name=row[3],
                    state=row[4],
                    printerval_status=row[5],
                    version=row[6],
                    image_url=image_url,
                    custom_config=row[9],
                )
            )
        return result

    def list_historical_images(
        self,
        *,
        model_version: str,
        embedding_dim: int,
    ) -> list[HistoricalImage]:
        query = f"""
            SELECT e.asset_id, e.embedding, e.embedding_dim, e.model_version,
                   e.phash, e.color_l, e.color_a, e.color_b,
                   a.url,
                   historical.job_id, historical.external_order_id,
                   historical.product_name
            FROM {COMPARISON_SCHEMA}.image_embeddings e
            JOIN {COMPARISON_SCHEMA}.image_assets a ON a.id = e.asset_id
            LEFT JOIN LATERAL (
                SELECT hj.id AS job_id, hj.external_order_id, hj.product_name
                FROM {COMPARISON_SCHEMA}.job_images ji
                JOIN {COMPARISON_SCHEMA}.historical_jobs hj ON hj.id = ji.job_id
                WHERE ji.asset_id = e.asset_id
                ORDER BY ji.is_primary DESC, ji.position ASC, hj.id ASC
                LIMIT 1
            ) historical ON TRUE
            WHERE e.model_version = %s AND e.embedding_dim = %s
            ORDER BY e.asset_id
        """
        rows = self.connection.execute(query, (model_version, embedding_dim)).fetchall()
        result: list[HistoricalImage] = []
        for row in rows:
            try:
                vector = _decode_embedding(row[1], embedding_dim)
            except ValueError as exc:
                logger.warning("skip historical asset %s: %s", row[0], exc)
                continue
            result.append(
                HistoricalImage(
                    asset_id=_as_uuid(row[0]),
                    job_id=_as_uuid(row[9]) if row[9] else None,
                    external_order_id=str(row[10]) if row[10] else None,
                    product_name=row[11],
                    image_url=str(row[8]),
                    embedding=vector,
                    embedding_dim=int(row[2]),
                    model_version=str(row[3]),
                    phash=str(row[4]),
                    color_lab=(float(row[5]), float(row[6]), float(row[7])),
                )
            )
        return result

    def create_run(
        self,
        *,
        source_kind: str,
        platform_id: uuid.UUID | None,
        model_version: str,
        embedding_dim: int,
        classifier_version: str,
        baseline_count: int,
        requested_count: int,
        promote_new_images: bool,
    ) -> uuid.UUID:
        run_id = uuid.uuid4()
        self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.comparison_runs
                (id, source_kind, platform_id, model_version, embedding_dim,
                 classifier_version, baseline_count, requested_count,
                 promote_new_images)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                source_kind,
                platform_id,
                model_version,
                embedding_dim,
                classifier_version,
                baseline_count,
                requested_count,
                promote_new_images,
            ),
        )
        self.connection.commit()
        return run_id

    def create_item(self, run_id: uuid.UUID, order: SourceOrder, model_version: str) -> uuid.UUID:
        item_id = uuid.uuid4()
        self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.comparison_items
                (id, run_id, platform_id, order_id, external_order_id,
                 product_name, source_state, source_printerval_status,
                 source_order_version, image_url, image_url_sha256,
                 model_version, processing_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'processing')
            """,
            (
                item_id,
                run_id,
                order.platform_id,
                order.order_id,
                order.external_order_id,
                order.product_name,
                order.state,
                order.printerval_status,
                order.version,
                order.image_url,
                _sha256_text(order.image_url),
                model_version,
            ),
        )
        self.connection.commit()
        return item_id

    def complete_item(
        self,
        *,
        item_id: uuid.UUID,
        embedding: np.ndarray,
        phash: str,
        color_lab: tuple[float, float, float],
        classification: str,
        is_duplicate: bool,
        candidates: Sequence[CandidateResult],
    ) -> None:
        self.connection.execute(
            f"""
            UPDATE {COMPARISON_SCHEMA}.comparison_items
            SET embedding = %s, embedding_dim = %s, phash = %s,
                color_l = %s, color_a = %s, color_b = %s,
                classification = %s, is_duplicate = %s,
                review_status = CASE WHEN %s THEN 'pending_review' ELSE 'no_match' END,
                processing_status = 'completed', last_error = NULL,
                updated_at = now()
            WHERE id = %s
            """,
            (
                embedding.astype("<f4").tobytes(),
                int(embedding.size),
                phash,
                color_lab[0],
                color_lab[1],
                color_lab[2],
                classification,
                is_duplicate,
                is_duplicate,
                item_id,
            ),
        )
        for candidate in candidates:
            self.connection.execute(
                f"""
                INSERT INTO {COMPARISON_SCHEMA}.comparison_candidates
                    (id, comparison_item_id, historical_job_id, historical_asset_id,
                     matched_external_order_id, matched_product_name, matched_image_url,
                     rank, visual_similarity, phash_distance, ssim, color_delta_e,
                     classification, confidence, reasons, classifier_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (comparison_item_id, historical_asset_id, classifier_version)
                DO UPDATE SET
                    rank = EXCLUDED.rank,
                    visual_similarity = EXCLUDED.visual_similarity,
                    phash_distance = EXCLUDED.phash_distance,
                    ssim = EXCLUDED.ssim,
                    color_delta_e = EXCLUDED.color_delta_e,
                    classification = EXCLUDED.classification,
                    confidence = EXCLUDED.confidence,
                    reasons = EXCLUDED.reasons,
                    decision_status = 'pending'
                """,
                (
                    uuid.uuid4(),
                    item_id,
                    candidate.historical.job_id,
                    candidate.historical.asset_id,
                    candidate.historical.external_order_id,
                    candidate.historical.product_name,
                    candidate.historical.image_url,
                    candidate.rank,
                    candidate.visual_similarity,
                    candidate.phash_distance,
                    candidate.ssim,
                    candidate.color_delta_e,
                    candidate.classification,
                    candidate.confidence,
                    Jsonb(candidate.reasons),
                    CLASSIFIER_VERSION,
                ),
            )
        self.connection.commit()

    def promote_item(
        self,
        *,
        item_id: uuid.UUID,
        run_id: uuid.UUID,
        order: SourceOrder,
        image_url: str,
        embedding: np.ndarray,
        phash: str,
        color_lab: tuple[float, float, float],
        model_version: str,
    ) -> None:
        """Append a successfully compared Waiting image to the history pool."""
        source_system = "tacahu_live"
        source_job_id = str(order.order_id)
        team_outsource = os.environ.get("PRINTERVAL_TEAM_OUTSOURCE", "unknown")[:128]
        status = (order.printerval_status or order.state or "waiting")[:16]
        product_name = (order.product_name or "")[:512]
        payload_hash = hashlib.sha256(
            f"{order.external_order_id}:{image_url}".encode()
        ).hexdigest()
        url_hash = _sha256_text(image_url)

        job_row = self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.historical_jobs
                (id, source_system, source_job_id, external_order_id, status,
                 team_outsource, job_type, order_id, product_name, preview_url,
                 preview_missing, source_payload_hash, ingest_source,
                 custom_config, custom_config_synced_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'all', %s, %s, %s, false, %s,
                    'live_waiting', %s, now())
            ON CONFLICT (source_system, source_job_id) DO UPDATE SET
                external_order_id = EXCLUDED.external_order_id,
                status = EXCLUDED.status,
                team_outsource = EXCLUDED.team_outsource,
                order_id = EXCLUDED.order_id,
                product_name = EXCLUDED.product_name,
                preview_url = EXCLUDED.preview_url,
                preview_missing = false,
                source_payload_hash = EXCLUDED.source_payload_hash,
                ingest_source = EXCLUDED.ingest_source,
                custom_config = EXCLUDED.custom_config,
                custom_config_synced_at = now(),
                last_seen_at = now()
            RETURNING id
            """,
            (
                uuid.uuid4(),
                source_system,
                source_job_id,
                order.external_order_id,
                status,
                team_outsource,
                str(order.order_id),
                product_name,
                image_url,
                payload_hash,
                Jsonb(order.custom_config) if order.custom_config else None,
            ),
        ).fetchone()
        if not job_row:
            raise RuntimeError(f"could not promote historical job for {order.external_order_id}")
        job_id = _as_uuid(job_row[0])

        asset_row = self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.image_assets
                (id, source_system, url_sha256, raw_url, url, fetch_status,
                 content_sha256, width, height)
            VALUES (%s, %s, %s, %s, %s, 'embedded', NULL, NULL, NULL)
            ON CONFLICT (source_system, url_sha256) DO UPDATE SET
                url = EXCLUDED.url,
                fetch_status = 'embedded',
                last_error = NULL,
                last_seen_at = now()
            RETURNING id
            """,
            (uuid.uuid4(), source_system, url_hash, image_url, image_url),
        ).fetchone()
        if not asset_row:
            raise RuntimeError(f"could not promote image asset for {order.external_order_id}")
        asset_id = _as_uuid(asset_row[0])

        self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.job_images
                (id, job_id, asset_id, role, position, is_primary)
            VALUES (%s, %s, %s, 'preview', 0, true)
            ON CONFLICT (job_id, role, position) DO UPDATE SET
                asset_id = EXCLUDED.asset_id,
                is_primary = true
            """,
            (uuid.uuid4(), job_id, asset_id),
        )
        self.connection.execute(
            f"""
            INSERT INTO {COMPARISON_SCHEMA}.image_embeddings
                (asset_id, model_version, embedding, embedding_dim, phash,
                 color_l, color_a, color_b)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_id, model_version) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                embedding_dim = EXCLUDED.embedding_dim,
                phash = EXCLUDED.phash,
                color_l = EXCLUDED.color_l,
                color_a = EXCLUDED.color_a,
                color_b = EXCLUDED.color_b,
                created_at = now()
            """,
            (
                asset_id,
                model_version,
                embedding.astype("<f4").tobytes(),
                int(embedding.size),
                phash,
                color_lab[0],
                color_lab[1],
                color_lab[2],
            ),
        )
        self.connection.execute(
            f"""
            UPDATE {COMPARISON_SCHEMA}.comparison_items
            SET pool_promoted_at = now(), pool_promotion_error = NULL, updated_at = now()
            WHERE id = %s
            """,
            (item_id,),
        )
        self.connection.commit()

    def record_promotion_error(self, item_id: uuid.UUID, message: str) -> None:
        self.connection.execute(
            f"""
            UPDATE {COMPARISON_SCHEMA}.comparison_items
            SET pool_promotion_error = %s, updated_at = now()
            WHERE id = %s
            """,
            (message[:2000], item_id),
        )
        self.connection.commit()

    def fail_item(self, item_id: uuid.UUID, message: str) -> None:
        self.connection.execute(
            f"""
            UPDATE {COMPARISON_SCHEMA}.comparison_items
            SET processing_status = 'failed', last_error = %s, updated_at = now()
            WHERE id = %s
            """,
            (message[:2000], item_id),
        )
        self.connection.commit()

    def finish_run(self, run_id: uuid.UUID, *, status: str, last_error: str | None = None) -> None:
        self.connection.execute(
            f"""
            UPDATE {COMPARISON_SCHEMA}.comparison_runs r
            SET run_status = %s,
                processed_count = (
                    SELECT COUNT(*) FROM {COMPARISON_SCHEMA}.comparison_items i
                    WHERE i.run_id = r.id AND i.processing_status = 'completed'
                ),
                duplicate_count = (
                    SELECT COUNT(*) FROM {COMPARISON_SCHEMA}.comparison_items i
                    WHERE i.run_id = r.id AND i.is_duplicate IS TRUE
                ),
                error_count = (
                    SELECT COUNT(*) FROM {COMPARISON_SCHEMA}.comparison_items i
                    WHERE i.run_id = r.id AND i.processing_status = 'failed'
                ),
                last_error = %s,
                finished_at = now()
            WHERE r.id = %s
            """,
            (status, last_error[:2000] if last_error else None, run_id),
        )
        self.connection.commit()


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
    old_image_cache: _ImageCache,
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


def _get_embedder(model_name: str) -> DinoV2Embedder:
    """Keep the model resident while the local worker processes multiple jobs."""
    embedder = _EMBEDDER_CACHE.get(model_name)
    if embedder is None:
        logger.info("loading Hugging Face model %s", model_name)
        embedder = DinoV2Embedder(model_name)
        _EMBEDDER_CACHE[model_name] = embedder
    return embedder


def run_comparison(
    database_url: str,
    *,
    source_kind: str,
    model_name: str = DEFAULT_MODEL_NAME,
    model_version: str | None = None,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    platform_id: uuid.UUID | None = None,
    order_ids: Sequence[uuid.UUID] = (),
    limit: int | None = 10,
    top_k: int = TOP_K_CANDIDATES,
    embedding_batch_size: int = 16,
    fetch_timeout: float = 30.0,
    exclude_self: bool = True,
    promote_new_images: bool = False,
) -> dict[str, Any]:
    """Run one durable comparison batch and return a JSON-safe summary."""
    if source_kind == "review" and promote_new_images:
        raise ValueError("review test orders cannot be promoted into the historical pool")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if embedding_batch_size <= 0:
        raise ValueError("embedding_batch_size must be positive")

    embedder = _get_embedder(model_name)
    resolved_model_version = model_version or embedder.name
    if resolved_model_version != embedder.name:
        logger.warning(
            "MODEL_VERSION=%s differs from EMBEDDING_MODEL_NAME=%s; the database pool "
            "must use the explicit model version",
            resolved_model_version,
            embedder.name,
        )

    with psycopg.connect(_psycopg_url(database_url)) as connection:
        repository = PostgresComparisonRepository(connection)
        orders = repository.list_source_orders(
            source_kind=source_kind,
            model_version=resolved_model_version,
            limit=limit,
            platform_id=platform_id,
            order_ids=order_ids,
        )
        historical = repository.list_historical_images(
            model_version=resolved_model_version,
            embedding_dim=embedding_dim,
        )
        pool_matrix = np.stack([item.embedding for item in historical]).astype(np.float32) if historical else np.empty((0, embedding_dim), dtype=np.float32)
        run_id = repository.create_run(
            source_kind=source_kind,
            platform_id=platform_id,
            model_version=resolved_model_version,
            embedding_dim=embedding_dim,
            classifier_version=CLASSIFIER_VERSION,
            baseline_count=len(historical),
            requested_count=len(orders),
            promote_new_images=promote_new_images,
        )
        old_image_cache = _ImageCache()
        completed = 0
        failed = 0
        duplicate_count = 0
        # Orders of one batch never match each other; they are added to the
        # pool together once the whole batch has been compared.
        to_promote: list[tuple[uuid.UUID, SourceOrder, np.ndarray, str, tuple[float, float, float]]] = []

        try:
            for start in range(0, len(orders), embedding_batch_size):
                batch_orders = orders[start : start + embedding_batch_size]
                prepared: list[tuple[SourceOrder, uuid.UUID, Image.Image]] = []
                for order in batch_orders:
                    item_id = repository.create_item(run_id, order, resolved_model_version)
                    try:
                        image = _fetch_image(order.image_url, timeout=fetch_timeout)
                        prepared.append((order, item_id, image))
                    except Exception as exc:
                        failed += 1
                        repository.fail_item(item_id, f"{type(exc).__name__}: {exc}")
                        logger.exception("image fetch failed for order %s", order.external_order_id)

                if not prepared:
                    continue

                try:
                    images = [image for _, _, image in prepared]
                    embeddings = embedder.encode_batch(images)
                    if len(embeddings) != len(prepared):
                        raise ValueError(
                            f"embedding batch size mismatch: expected {len(prepared)}, got {len(embeddings)}"
                        )
                except Exception as exc:
                    connection.rollback()
                    for order, item_id, _ in prepared:
                        failed += 1
                        repository.fail_item(item_id, f"{type(exc).__name__}: {exc}")
                    logger.exception("embedding batch failed for %s orders", len(prepared))
                    continue

                for (order, item_id, image), embedding in zip(prepared, embeddings):
                    try:
                        if embedding.size != embedding_dim:
                            raise ValueError(
                                f"new embedding dimension mismatch: expected {embedding_dim}, got {embedding.size}"
                            )
                        embedding = np.asarray(embedding, dtype=np.float32)
                        overall, is_duplicate, phash, lab, candidates = compare_image_to_pool(
                            image,
                            embedding,
                            external_order_id=order.external_order_id,
                            pool=historical,
                            pool_matrix=pool_matrix,
                            top_k=top_k,
                            old_image_cache=old_image_cache,
                            fetch_timeout=fetch_timeout,
                            exclude_self=exclude_self,
                        )
                        repository.complete_item(
                            item_id=item_id,
                            embedding=embedding,
                            phash=phash,
                            color_lab=lab,
                            classification=overall,
                            is_duplicate=is_duplicate,
                            candidates=candidates,
                        )
                        if promote_new_images:
                            to_promote.append((item_id, order, embedding, phash, lab))
                        completed += 1
                        duplicate_count += int(is_duplicate)
                        logger.info(
                            "compared order=%s status=%s duplicate=%s candidates=%s",
                            order.external_order_id,
                            source_kind,
                            is_duplicate,
                            len(candidates),
                        )
                    except Exception as exc:
                        failed += 1
                        connection.rollback()
                        repository.fail_item(item_id, f"{type(exc).__name__}: {exc}")
                        logger.exception("comparison failed for order %s", order.external_order_id)

            for item_id, order, embedding, phash, lab in to_promote:
                try:
                    repository.promote_item(
                        item_id=item_id,
                        run_id=run_id,
                        order=order,
                        image_url=order.image_url,
                        embedding=embedding,
                        phash=phash,
                        color_lab=lab,
                        model_version=resolved_model_version,
                    )
                except Exception as exc:
                    connection.rollback()
                    repository.record_promotion_error(item_id, f"{type(exc).__name__}: {exc}")
                    logger.exception("pool promotion failed for order %s", order.external_order_id)

            repository.finish_run(run_id, status="completed")
        except Exception as exc:
            repository.finish_run(run_id, status="failed", last_error=f"{type(exc).__name__}: {exc}")
            raise

    return {
        "run_id": str(run_id),
        "run_status": "completed",
        "source_kind": source_kind,
        "model_version": resolved_model_version,
        "embedding_dim": embedding_dim,
        "baseline_count": len(historical),
        "requested_count": len(orders),
        "processed_count": completed,
        "duplicate_count": duplicate_count,
        "error_count": failed,
        "self_match_excluded": exclude_self,
        "promote_new_images": promote_new_images,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Tacahu PostgreSQL orders with the historical DINOv2 image pool"
    )
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--source",
        choices=("review", "waiting", "support_unchecked", "manual"),
        default="review",
    )
    parser.add_argument("--platform-id", type=uuid.UUID)
    parser.add_argument("--order-id", action="append", type=uuid.UUID, default=[])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=TOP_K_CANDIDATES)
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("EMBEDDING_BATCH_SIZE", "16")))
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL_NAME", DEFAULT_MODEL_NAME))
    parser.add_argument("--model-version", default=os.environ.get("MODEL_VERSION"))
    parser.add_argument("--embedding-dim", type=int, default=int(os.environ.get("EMBEDDING_DIM", DEFAULT_EMBEDDING_DIM)))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("IMAGE_FETCH_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--include-self", action="store_true", help="allow the same external order to match itself")
    parser.add_argument("--confirm", action="store_true", help="confirm PostgreSQL writes")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    if not args.database_url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        return 2
    if not args.confirm:
        print("ERROR: comparison writes PostgreSQL; pass --confirm", file=sys.stderr)
        return 2
    if args.source == "waiting" and args.include_self:
        logger.warning("self-match exclusion disabled")
    try:
        summary = run_comparison(
            args.database_url,
            source_kind=args.source,
            model_name=args.model,
            model_version=args.model_version,
            embedding_dim=args.embedding_dim,
            platform_id=args.platform_id,
            order_ids=args.order_id,
            limit=args.limit,
            top_k=args.top_k,
            embedding_batch_size=args.batch_size,
            fetch_timeout=args.timeout,
            exclude_self=not args.include_self,
            promote_new_images=args.source in {"waiting", "support_unchecked"},
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
