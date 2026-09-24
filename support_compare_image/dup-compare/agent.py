"""Support compute agent: runs DINO comparison jobs and image searches on this machine.

The agent talks to the Tacahu API over HTTPS only (no database access, no SSH tunnel):

1. *Device login*: it prints a short code; a signed-in Support/Admin approves it on the web
   (Hàng đợi → "Cho phép máy này"). The API then hands the agent a token.
2. The token works only while that user keeps the web open (presence heartbeat). Closing the
   web, logging out or a 12 h expiry stops the agent; it then waits or asks for a new code.
3. While allowed, the agent claims a queued job (or image search) with a lease, downloads the
   image pool (once, then only the delta), embeds and compares on this machine's GPU/CPU and
   posts the results. If the lease is lost the work is dropped and another machine resumes it.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from backend.compare_core import (
    HistoricalImage,
    ImageCache,
    compare_image_to_pool,
    fetch_image,
    get_cached_embedder,
)
from PIL import Image

logger = logging.getLogger("support_compare.agent")

LEASE_LOST_STATUSES = (401, 403, 409)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class LeaseLost(Exception):
    """The API no longer lets this machine work on the item (presence lost, cancelled, re-claimed)."""


@dataclass(frozen=True)
class AgentConfig:
    api_url: str
    web_url: str
    machine_name: str
    home: Path
    model_name: str
    model_version: str
    embedding_dim: int
    batch_size: int
    top_k: int
    fetch_timeout: float
    poll_seconds: float
    heartbeat_seconds: float = 30.0
    pool_page_size: int = 2000


# --------------------------------------------------------------------------- HTTP


class Api:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 120.0):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: dict[str, Any] | None = None,
        raw: bool = False,
        auth: bool = True,
    ) -> Any:
        url = f"{self.base}/api/support-worker{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "User-Agent": "support-compare-agent/1"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            code, message = "http_error", exc.reason or ""
            try:
                detail = json.loads(exc.read()).get("detail")
                if isinstance(detail, dict):
                    code, message = detail.get("code", code), detail.get("message", message)
                elif detail:
                    message = str(detail)
            except (ValueError, AttributeError):
                pass
            raise ApiError(exc.code, code, str(message)) from exc
        return payload if raw else json.loads(payload)

    def start_login(self, machine_name: str) -> dict:
        return self._call("POST", "/device/start", body={"machine_name": machine_name}, auth=False)

    def poll_login(self, device_code: str) -> dict:
        return self._call("POST", "/device/poll", body={"device_code": device_code}, auth=False)

    def claim(self, model_version: str, embedding_dim: int) -> dict:
        return self._call("POST", "/claim", body={"model_version": model_version, "embedding_dim": embedding_dim})

    def pool(self, model_version: str, embedding_dim: int, after: str | None, limit: int) -> dict:
        return self._call(
            "GET",
            "/pool",
            params={"model_version": model_version, "embedding_dim": embedding_dim, "after": after, "limit": limit},
        )

    def heartbeat_job(self, job_id: str) -> None:
        self._call("POST", f"/jobs/{job_id}/heartbeat", body={})

    def submit_items(self, job_id: str, items: list[dict]) -> dict:
        return self._call("POST", f"/jobs/{job_id}/items", body={"items": items})

    def complete_job(self, job_id: str, baseline_count: int) -> dict:
        return self._call("POST", f"/jobs/{job_id}/complete", body={"baseline_count": baseline_count})

    def fail_job(self, job_id: str, error: str) -> None:
        self._call("POST", f"/jobs/{job_id}/fail", body={"error": error[:4000]})

    def search_image(self, search_id: str) -> bytes:
        return self._call("GET", f"/search/{search_id}/image", raw=True)

    def heartbeat_search(self, search_id: str) -> None:
        self._call("POST", f"/search/{search_id}/heartbeat", body={})

    def search_result(self, search_id: str, result: dict) -> None:
        self._call("POST", f"/search/{search_id}/result", body={"result": result})

    def search_fail(self, search_id: str, error: str) -> None:
        self._call("POST", f"/search/{search_id}/fail", body={"error": error[:4000]})


# --------------------------------------------------------------------------- pool


def _historical(item: dict, embedding_dim: int, model_version: str) -> HistoricalImage:
    vector = np.frombuffer(base64.b64decode(item["embedding"]), dtype="<f4").astype(np.float32, copy=True)
    if vector.size != embedding_dim:
        raise ValueError(f"pool embedding dimension mismatch: {vector.size} != {embedding_dim}")
    lab = item["lab"]
    return HistoricalImage(
        asset_id=uuid.UUID(item["asset_id"]),
        job_id=uuid.UUID(item["job_id"]) if item.get("job_id") else None,
        external_order_id=item.get("external_order_id"),
        product_name=item.get("product_name"),
        image_url=item["image_url"],
        embedding=vector,
        embedding_dim=embedding_dim,
        model_version=model_version,
        phash=item["phash"],
        color_lab=(float(lab[0]), float(lab[1]), float(lab[2])),
    )


class Pool:
    """The historical pool in memory, synced incrementally (keyset cursor) from the API."""

    def __init__(self, model_version: str, embedding_dim: int, page_size: int = 2000):
        self.model_version = model_version
        self.embedding_dim = embedding_dim
        self.page_size = page_size
        self.rows: dict[uuid.UUID, HistoricalImage] = {}
        self.cursor: str | None = None
        self.synced_once = False
        self._matrix: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def sync(self, api: Api, should_stop: Callable[[], bool] = lambda: False) -> int:
        received = 0
        while True:
            if should_stop():
                raise LeaseLost("stopped while syncing the pool")
            page = api.pool(self.model_version, self.embedding_dim, self.cursor, self.page_size)
            for item in page["items"]:
                row = _historical(item, self.embedding_dim, self.model_version)
                self.rows[row.asset_id] = row  # a re-embedded asset replaces its old vector
                received += 1
            if page.get("cursor"):
                self.cursor = page["cursor"]
            if received:
                self._matrix = None
            if not page.get("next_cursor"):
                break
            logger.info("pool sync: %s rows so far", len(self.rows))
        self.synced_once = True
        return received

    def snapshot(self) -> tuple[list[HistoricalImage], np.ndarray]:
        rows = list(self.rows.values())
        if self._matrix is None or len(self._matrix) != len(rows):
            self._matrix = (
                np.stack([r.embedding for r in rows]).astype(np.float32)
                if rows
                else np.empty((0, self.embedding_dim), dtype=np.float32)
            )
        return rows, self._matrix


# --------------------------------------------------------------------------- lease


class Lease:
    """Heartbeat thread for the item being worked on; ``lost`` is set when the API drops us."""

    def __init__(self, beat: Callable[[], None], interval: float):
        self._beat = beat
        self._interval = interval
        self.lost = threading.Event()
        self.reason = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._beat()
            except ApiError as exc:
                if exc.status in LEASE_LOST_STATUSES:
                    self.reason = exc.message
                    self.lost.set()
                    return
                logger.warning("heartbeat failed: %s", exc)
            except OSError as exc:  # network blip: the lease survives a few missed beats
                logger.warning("heartbeat network error: %s", exc)

    def check(self) -> None:
        if self.lost.is_set():
            raise LeaseLost(self.reason or "lease lost")

    def __enter__(self) -> Lease:
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._stop.set()


# --------------------------------------------------------------------------- work


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _candidate_payload(candidate) -> dict:
    historical = candidate.historical
    return {
        "historical_job_id": str(historical.job_id) if historical.job_id else None,
        "historical_asset_id": str(historical.asset_id),
        "matched_external_order_id": historical.external_order_id,
        "matched_product_name": historical.product_name,
        "matched_image_url": historical.image_url,
        "rank": candidate.rank,
        "visual_similarity": float(candidate.visual_similarity),
        "phash_distance": int(candidate.phash_distance),
        "ssim": None if candidate.ssim is None else float(candidate.ssim),
        "color_delta_e": float(candidate.color_delta_e),
        "classification": candidate.classification,
        "confidence": float(candidate.confidence),
        "reasons": [str(r) for r in candidate.reasons],
    }


def _failed(order: dict, exc: Exception) -> dict:
    return {"order_id": order["order_id"], "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:2000]}


def process_orders(
    api: Api, embedder, pool: Pool, cfg: AgentConfig, job: dict, lease: Lease, fetch=None
) -> dict[str, int]:
    """Embed and compare the job's orders against the pool snapshot taken now, batch by batch."""
    fetch = fetch or fetch_image
    rows, matrix = pool.snapshot()
    cache = ImageCache()
    counts = {"stored": 0, "failed": 0, "skipped": 0}
    orders = job["orders"]
    done = 0
    for batch in _chunks(orders, cfg.batch_size):
        lease.check()
        payloads: list[dict] = []
        prepared: list[tuple[dict, Image.Image]] = []
        for order in batch:
            try:
                prepared.append((order, fetch(order["image_url"], timeout=cfg.fetch_timeout)))
            except Exception as exc:
                logger.warning("image fetch failed for %s: %s", order["external_order_id"], exc)
                payloads.append(_failed(order, exc))
        if prepared:
            try:
                embeddings = embedder.encode_batch([image for _, image in prepared])
                if len(embeddings) != len(prepared):
                    raise ValueError(f"embedding batch size mismatch: {len(embeddings)} != {len(prepared)}")
            except Exception as exc:
                logger.exception("embedding failed for %s orders", len(prepared))
                payloads.extend(_failed(order, exc) for order, _ in prepared)
                prepared = []
                embeddings = []
            for (order, image), embedding in zip(prepared, embeddings):
                try:
                    embedding = np.asarray(embedding, dtype=np.float32)
                    if embedding.size != cfg.embedding_dim:
                        raise ValueError(f"embedding dimension {embedding.size} != {cfg.embedding_dim}")
                    overall, is_duplicate, phash, lab, candidates = compare_image_to_pool(
                        image,
                        embedding,
                        external_order_id=order["external_order_id"],
                        pool=rows,
                        pool_matrix=matrix,
                        top_k=cfg.top_k,
                        old_image_cache=cache,
                        fetch_timeout=cfg.fetch_timeout,
                        exclude_self=True,
                    )
                    payloads.append(
                        {
                            "order_id": order["order_id"],
                            "status": "completed",
                            "embedding_b64": base64.b64encode(embedding.astype("<f4").tobytes()).decode(),
                            "phash": phash,
                            "lab": [float(v) for v in lab],
                            "classification": overall,
                            "is_duplicate": bool(is_duplicate),
                            "candidates": [_candidate_payload(c) for c in candidates],
                        }
                    )
                    logger.info("compared %s duplicate=%s", order["external_order_id"], is_duplicate)
                except Exception as exc:
                    logger.exception("comparison failed for %s", order["external_order_id"])
                    payloads.append(_failed(order, exc))
        result = api.submit_items(job["id"], payloads)
        for key in counts:
            counts[key] += int(result.get(key, 0))
        done += len(batch)
        logger.info("job %s: %s/%s orders submitted", job["id"], done, len(orders))
    return counts


def run_job(api: Api, embedder, pool: Pool, cfg: AgentConfig, job: dict, fetch=None) -> None:
    job_id = job["id"]
    logger.info("claimed job %s (%s orders)", job_id, len(job["orders"]))
    try:
        with Lease(lambda: api.heartbeat_job(job_id), cfg.heartbeat_seconds) as lease:
            pool.sync(api, should_stop=lease.lost.is_set)
            counts = process_orders(api, embedder, pool, cfg, job, lease, fetch=fetch)
            lease.check()
            summary = api.complete_job(job_id, baseline_count=len(pool))
        logger.info("job %s completed: %s %s", job_id, counts, summary)
    except LeaseLost as exc:
        logger.warning("job %s dropped (%s); another machine can resume it", job_id, exc)
    except ApiError as exc:
        if exc.status in LEASE_LOST_STATUSES:
            logger.warning("job %s dropped: %s", job_id, exc)
            return
        _report_failure(api.fail_job, job_id, str(exc))
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        _report_failure(api.fail_job, job_id, f"{type(exc).__name__}: {exc}")


def _report_failure(send: Callable[[str, str], None], item_id: str, message: str) -> None:
    try:
        send(item_id, message)
    except Exception:
        logger.exception("cannot report the failure of %s", item_id)


def run_search(api: Api, embedder, pool: Pool, cfg: AgentConfig, search: dict) -> None:
    search_id = search["id"]
    logger.info("claimed image search %s", search_id)
    started = time.time()
    try:
        with Lease(lambda: api.heartbeat_search(search_id), cfg.heartbeat_seconds) as lease:
            data = api.search_image(search_id)
            image = Image.open(io.BytesIO(data)).convert("RGB")
            pool.sync(api, should_stop=lease.lost.is_set)
            rows, matrix = pool.snapshot()
            if not rows:
                raise ValueError(f"Pool chưa có embedding nào cho model {cfg.model_version}")
            embedding = np.asarray(embedder.encode_batch([image])[0], dtype=np.float32)
            overall, is_duplicate, _phash, _lab, candidates = compare_image_to_pool(
                image,
                embedding,
                external_order_id="",
                pool=rows,
                pool_matrix=matrix,
                top_k=int(search["top_k"]),
                old_image_cache=ImageCache(),
                fetch_timeout=cfg.fetch_timeout,
                exclude_self=False,
            )
            lease.check()
            api.search_result(
                search_id,
                {
                    "verdict": overall,
                    "is_duplicate": bool(is_duplicate),
                    "pool_count": len(rows),
                    "model_version": cfg.model_version,
                    "elapsed_ms": round((time.time() - started) * 1000),
                    "candidates": [
                        {
                            "rank": c.rank,
                            "order_code": c.historical.external_order_id,
                            "product_name": c.historical.product_name,
                            "image_url": c.historical.image_url,
                            "similarity": float(c.visual_similarity),
                            "phash_distance": int(c.phash_distance),
                            "ssim": None if c.ssim is None else float(c.ssim),
                            "color_delta_e": float(c.color_delta_e),
                            "classification": c.classification,
                            "reasons": [str(r) for r in c.reasons],
                            "historical_job_id": str(c.historical.job_id) if c.historical.job_id else None,
                        }
                        for c in candidates
                    ],
                },
            )
    except LeaseLost as exc:
        logger.warning("search %s dropped (%s)", search_id, exc)
    except ApiError as exc:
        if exc.status in LEASE_LOST_STATUSES:
            logger.warning("search %s dropped: %s", search_id, exc)
            return
        _report_failure(api.search_fail, search_id, str(exc))
    except Exception as exc:
        logger.exception("search %s failed", search_id)
        _report_failure(api.search_fail, search_id, f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- login / main loop


def _token_file(cfg: AgentConfig) -> Path:
    return cfg.home / "token"


def load_token(cfg: AgentConfig) -> str | None:
    try:
        return _token_file(cfg).read_text().strip() or None
    except OSError:
        return None


def save_token(cfg: AgentConfig, token: str | None) -> None:
    path = _token_file(cfg)
    if token is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(0o600)


def device_login(api: Api, cfg: AgentConfig, sleep: Callable[[float], None] = time.sleep) -> str:
    """Show a code, wait until a signed-in Support allows this machine, return the token."""
    while True:
        start = api.start_login(cfg.machine_name)
        base = start.get("verification_uri") or (f"{cfg.web_url.rstrip('/')}/support-queue" if cfg.web_url else "")
        link = f"{base}?code={start['user_code']}" if base else "(mở web Tacahu → Hàng đợi)"
        logger.info("=" * 64)
        logger.info("Cho phép máy này chạy job: mở %s", link)
        logger.info("Mã kết nối: %s  (hết hạn sau %s giây)", start["user_code"], start["expires_in"])
        logger.info("=" * 64)
        deadline = time.time() + int(start["expires_in"])
        while time.time() < deadline:
            sleep(float(start.get("interval", 3)))
            result = api.poll_login(start["device_code"])
            if result["status"] == "approved":
                logger.info("Đã được cho phép, bắt đầu nhận job.")
                return result["token"]
            if result["status"] in ("denied", "expired"):
                break
        logger.info("Mã hết hạn, lấy mã mới...")


def run_agent(cfg: AgentConfig, *, once: bool = False, api: Api | None = None, embedder=None) -> int:
    api = api or Api(cfg.api_url, load_token(cfg))
    pool = Pool(cfg.model_version, cfg.embedding_dim, cfg.pool_page_size)
    waiting_note = ""
    while True:
        try:
            if not api.token:
                api.token = device_login(api, cfg)
                save_token(cfg, api.token)
            if embedder is None:
                embedder = get_cached_embedder(cfg.model_name)
            if not pool.synced_once:
                logger.info("đồng bộ pool ảnh lần đầu...")
                pool.sync(api)
                logger.info("pool: %s ảnh", len(pool))
            work = api.claim(cfg.model_version, cfg.embedding_dim)
            waiting_note = ""
        except ApiError as exc:
            if exc.status == 401:
                logger.warning("token không còn hiệu lực (%s); kết nối lại", exc.message)
                api.token = None
                save_token(cfg, None)
                continue
            note = f"{exc.code}: {exc.message}"
            if note != waiting_note:
                logger.info("Tạm dừng: %s", exc.message)
                waiting_note = note
            if once:
                return 1
            time.sleep(cfg.poll_seconds)
            continue
        except LeaseLost:
            time.sleep(cfg.poll_seconds)
            continue
        except OSError as exc:
            logger.warning("mất kết nối tới API: %s", exc)
            if once:
                return 1
            time.sleep(cfg.poll_seconds)
            continue

        if work["kind"] == "job":
            run_job(api, embedder, pool, cfg, work["job"])
        elif work["kind"] == "search":
            run_search(api, embedder, pool, cfg, work["search"])
        elif once:
            return 0
        else:
            time.sleep(cfg.poll_seconds)
        if once:
            return 0


# --------------------------------------------------------------------------- CLI


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def build_config(argv: list[str] | None = None) -> tuple[AgentConfig, bool]:
    parser = argparse.ArgumentParser(description="Support compute agent (DINO on this machine)")
    parser.add_argument("--api-url", default=os.environ.get("SUPPORT_API_URL", ""))
    parser.add_argument("--web-url", default=os.environ.get("SUPPORT_WEB_URL", ""))
    parser.add_argument("--name", default=os.environ.get("AGENT_NAME") or socket.gethostname())
    parser.add_argument("--home", default=os.environ.get("AGENT_HOME") or str(Path.home() / ".support-agent"))
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL_NAME", "facebook/dinov2-base"))
    parser.add_argument("--model-version", default=os.environ.get("MODEL_VERSION"))
    parser.add_argument("--embedding-dim", type=int, default=_env_int("EMBEDDING_DIM", 768))
    parser.add_argument("--batch-size", type=int, default=_env_int("EMBEDDING_BATCH_SIZE", 16))
    parser.add_argument("--top-k", type=int, default=_env_int("TOP_K_CANDIDATES", 10))
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("IMAGE_FETCH_TIMEOUT_SECONDS", "30")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.environ.get("AGENT_POLL_SECONDS", "5")))
    parser.add_argument("--once", action="store_true", help="claim at most one item, then exit")
    args = parser.parse_args(argv)
    if not args.api_url:
        parser.error("SUPPORT_API_URL (hoặc --api-url) là bắt buộc")
    cfg = AgentConfig(
        api_url=args.api_url,
        web_url=args.web_url,
        machine_name=args.name,
        home=Path(args.home),
        model_name=args.model,
        model_version=args.model_version or args.model,
        embedding_dim=args.embedding_dim,
        batch_size=args.batch_size,
        top_k=args.top_k,
        fetch_timeout=args.timeout,
        poll_seconds=args.poll_seconds,
    )
    return cfg, args.once


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg, once = build_config(argv)
    return run_agent(cfg, once=once)


if __name__ == "__main__":
    raise SystemExit(main())
