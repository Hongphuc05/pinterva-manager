"""Agent behaviour against a fake API and a fake embedder (no network, no model)."""

from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path

import agent
import numpy as np
import pytest
from PIL import Image

DIM = 4


def _cfg(tmp_path: Path, **over) -> agent.AgentConfig:
    values = dict(
        api_url="https://api.test", web_url="https://web.test", machine_name="Mac Test", home=tmp_path,
        model_name="m", model_version="m", embedding_dim=DIM, batch_size=2, top_k=3, fetch_timeout=1.0,
        poll_seconds=0.01, heartbeat_seconds=0.05, pool_page_size=2,
    )
    values.update(over)
    return agent.AgentConfig(**values)


def _pool_item(value: float, code: str) -> dict:
    vec = np.array([value, 1 - value, 0, 0], dtype="<f4")
    vec /= np.linalg.norm(vec)
    return {
        "asset_id": str(uuid.uuid4()), "embedding": base64.b64encode(vec.tobytes()).decode(),
        "phash": "0" * 64, "lab": [50.0, 0.0, 0.0], "image_url": f"https://old.test/{code}.png",
        "job_id": str(uuid.uuid4()), "external_order_id": code, "product_name": f"Old {code}",
    }


class FakeApi:
    """Records calls; pool pages are served two rows at a time like the real keyset paging."""

    def __init__(self, pool_items: list[dict], *, heartbeat_error: agent.ApiError | None = None):
        self.token = "sw_x"
        self.pool_items = pool_items
        self.heartbeat_error = heartbeat_error
        self.pool_calls: list[str | None] = []
        self.submitted: list[dict] = []
        self.completed: dict | None = None
        self.failed: str | None = None
        self.heartbeats = 0
        self.search_results: list[dict] = []

    def pool(self, model_version, embedding_dim, after, limit):
        self.pool_calls.append(after)
        start = int(after or 0)
        page = self.pool_items[start : start + limit]
        end = start + len(page)
        return {"items": page, "cursor": str(end) if page else None, "next_cursor": str(end) if len(page) == limit else None}

    def heartbeat_job(self, job_id):
        self.heartbeats += 1
        if self.heartbeat_error:
            raise self.heartbeat_error

    heartbeat_search = heartbeat_job

    def submit_items(self, job_id, items):
        self.submitted.extend(items)
        return {"stored": sum(i["status"] == "completed" for i in items), "failed": sum(i["status"] == "failed" for i in items), "skipped": 0}

    def complete_job(self, job_id, baseline_count):
        self.completed = {"baseline_count": baseline_count}
        return {"processed_count": len(self.submitted)}

    def fail_job(self, job_id, error):
        self.failed = error

    def search_image(self, search_id):
        import io

        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), (10, 120, 200)).save(buffer, "PNG")
        return buffer.getvalue()

    def search_result(self, search_id, result):
        self.search_results.append(result)

    def search_fail(self, search_id, error):
        self.failed = error


class FakeEmbedder:
    name = "m"

    def encode_batch(self, images):
        return np.tile(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), (len(images), 1))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    image = Image.new("RGB", (32, 32), (200, 30, 30))
    monkeypatch.setattr(agent, "_fetch_image", lambda url, timeout=1.0: image)
    import backend.postgres_compare as pc

    monkeypatch.setattr(pc, "_fetch_image", lambda url, timeout=1.0: image)


def _job(count: int = 3) -> dict:
    return {
        "id": str(uuid.uuid4()), "run_id": str(uuid.uuid4()), "requested_count": count,
        "orders": [
            {"order_id": str(uuid.uuid4()), "external_order_id": f"DJ-{i}", "product_name": "P",
             "image_url": f"https://new.test/{i}.png"}
            for i in range(count)
        ],
    }


def test_pool_sync_pages_then_only_the_delta():
    items = [_pool_item(0.9, f"OLD-{i}") for i in range(5)]
    api = FakeApi(items)
    pool = agent.Pool("m", DIM, page_size=2)
    assert pool.sync(api) == 5 and len(pool) == 5 and pool.synced_once
    assert api.pool_calls == [None, "2", "4"]

    api.pool_items.append(_pool_item(0.8, "OLD-5"))
    assert pool.sync(api) == 1 and len(pool) == 6
    assert api.pool_calls[-1] == "5"  # continued from the last cursor, not from scratch


def test_pool_replaces_a_re_embedded_asset():
    item = _pool_item(0.9, "OLD-1")
    api = FakeApi([item])
    pool = agent.Pool("m", DIM, page_size=5)
    pool.sync(api)
    api.pool_items[:] = [{**item, "phash": "f" * 64}]
    pool.cursor = None
    pool.sync(api)
    assert len(pool) == 1 and next(iter(pool.rows.values())).phash == "f" * 64


def test_run_job_embeds_compares_submits_in_batches_and_completes(tmp_path):
    api = FakeApi([_pool_item(1.0, "OLD-SAME"), _pool_item(0.1, "OLD-FAR")])
    cfg = _cfg(tmp_path)
    pool = agent.Pool("m", DIM, page_size=10)
    job = _job(3)

    agent.run_job(api, FakeEmbedder(), pool, cfg, job)

    assert api.completed == {"baseline_count": 2} and api.failed is None
    assert [i["status"] for i in api.submitted] == ["completed"] * 3
    first = api.submitted[0]
    assert first["candidates"][0]["matched_external_order_id"] == "OLD-SAME"
    assert first["candidates"][0]["rank"] == 1 and len(first["candidates"]) <= cfg.top_k
    assert np.frombuffer(base64.b64decode(first["embedding_b64"]), dtype="<f4").size == DIM


def test_a_broken_image_is_reported_per_order_without_stopping_the_job(tmp_path, monkeypatch):
    image = Image.new("RGB", (32, 32), (1, 2, 3))

    def fetch(url, timeout=1.0):
        if url.endswith("/1.png"):
            raise OSError("404")
        return image

    monkeypatch.setattr(agent, "_fetch_image", fetch)
    api = FakeApi([_pool_item(1.0, "OLD")])
    pool = agent.Pool("m", DIM, page_size=10)
    agent.run_job(api, FakeEmbedder(), pool, _cfg(tmp_path), _job(3), fetch=fetch)

    statuses = {i["order_id"]: i["status"] for i in api.submitted}
    assert sorted(statuses.values()) == ["completed", "completed", "failed"]
    assert api.completed is not None


def test_losing_the_lease_drops_the_job_without_completing_or_failing_it(tmp_path):
    api = FakeApi([_pool_item(1.0, "OLD")], heartbeat_error=agent.ApiError(403, "presence_lost", "web closed"))

    class SlowEmbedder(FakeEmbedder):
        def encode_batch(self, images):
            time.sleep(0.15)  # let the heartbeat thread notice the lost lease between batches
            return super().encode_batch(images)

    pool = agent.Pool("m", DIM, page_size=10)
    agent.run_job(api, SlowEmbedder(), pool, _cfg(tmp_path), _job(8))

    assert api.completed is None and api.failed is None
    assert len(api.submitted) < 8  # stopped early instead of finishing everything


def test_an_unexpected_error_marks_the_job_failed(tmp_path):
    class BrokenApi(FakeApi):
        def submit_items(self, job_id, items):
            raise agent.ApiError(500, "http_error", "boom")

    api = BrokenApi([_pool_item(1.0, "OLD")])
    agent.run_job(api, FakeEmbedder(), agent.Pool("m", DIM, page_size=10), _cfg(tmp_path), _job(1))
    assert api.failed and "boom" in api.failed and api.completed is None


def test_search_returns_the_ranked_candidates(tmp_path):
    api = FakeApi([_pool_item(1.0, "OLD-A"), _pool_item(0.2, "OLD-B")])
    agent.run_search(api, FakeEmbedder(), agent.Pool("m", DIM, page_size=10), _cfg(tmp_path), {"id": "s1", "top_k": 2})
    result = api.search_results[0]
    assert result["pool_count"] == 2 and len(result["candidates"]) == 2
    assert result["candidates"][0]["order_code"] == "OLD-A" and result["candidates"][0]["rank"] == 1
    assert result["candidates"][0]["historical_job_id"]


def test_search_on_an_empty_pool_fails_the_search(tmp_path):
    api = FakeApi([])
    agent.run_search(api, FakeEmbedder(), agent.Pool("m", DIM, page_size=10), _cfg(tmp_path), {"id": "s1", "top_k": 5})
    assert api.search_results == [] and "Pool" in (api.failed or "")


def test_device_login_prints_a_code_and_returns_the_token_once_approved(tmp_path):
    class LoginApi:
        def __init__(self):
            self.polls = 0

        def start_login(self, name):
            assert name == "Mac Test"
            return {"device_code": "d" * 20, "user_code": "ABCD-2345", "verification_uri": None, "interval": 0, "expires_in": 60}

        def poll_login(self, code):
            self.polls += 1
            return {"status": "pending"} if self.polls < 3 else {"status": "approved", "token": "sw_tok"}

    api = LoginApi()
    assert agent.device_login(api, _cfg(tmp_path), sleep=lambda _s: None) == "sw_tok" and api.polls == 3


def test_token_is_stored_privately_and_cleared(tmp_path):
    cfg = _cfg(tmp_path / "home")
    assert agent.load_token(cfg) is None
    agent.save_token(cfg, "sw_secret")
    assert agent.load_token(cfg) == "sw_secret"
    assert (cfg.home / "token").stat().st_mode & 0o077 == 0
    agent.save_token(cfg, None)
    assert agent.load_token(cfg) is None


def test_run_agent_relogs_in_after_a_401_and_then_processes_one_job(tmp_path, monkeypatch):
    class LoopApi(FakeApi):
        def __init__(self):
            super().__init__([_pool_item(1.0, "OLD")])
            self.token = "sw_stale"
            self.claims = 0

        def claim(self, model_version, embedding_dim):
            self.claims += 1
            if self.claims == 1:
                raise agent.ApiError(401, "revoked", "Máy đã bị thu hồi quyền")
            return {"kind": "job", "job": _job(2)}

    api = LoopApi()
    monkeypatch.setattr(agent, "device_login", lambda a, c, sleep=None: "sw_fresh")
    rc = agent.run_agent(_cfg(tmp_path), once=True, api=api, embedder=FakeEmbedder())
    assert rc == 0 and api.token == "sw_fresh" and agent.load_token(_cfg(tmp_path)) == "sw_fresh"
    assert api.completed is not None


def test_run_agent_waits_while_the_web_is_closed(tmp_path):
    class PausedApi(FakeApi):
        def claim(self, model_version, embedding_dim):
            raise agent.ApiError(403, "presence_lost", "Chưa có Support mở web")

    assert agent.run_agent(_cfg(tmp_path), once=True, api=PausedApi([_pool_item(1.0, "O")]), embedder=FakeEmbedder()) == 1
