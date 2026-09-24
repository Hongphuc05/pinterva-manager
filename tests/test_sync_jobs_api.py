import uuid
from datetime import UTC, datetime, timedelta

from app.adapters.db.models import Order, Platform, SyncJob, User
from app.application.auth import hash_password
from app.application.sync_jobs import reclaim_stale_sync_jobs


def _admin_token(client, db_session):
    user = User(
        username="sync_jobs_admin",
        full_name="Sync Jobs Admin",
        role="admin",
        password_hash=hash_password("pass123"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    response = client.post("/api/login", json={"username": user.username, "password": "pass123"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_status_sync_job_is_platform_scoped_and_deduplicated(client, db_session, monkeypatch):
    """Double-clicking sync must reuse one queued job instead of duplicating work."""
    from app.api.routes import sync_jobs_api

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(sync_jobs_api, "_dispatch_status_job", lambda job_id: dispatched.append(job_id))
    token = _admin_token(client, db_session)
    platform = Platform(
        name="Sync platform",
        account_username="sync@printerval.com",
        session_cookie="server-only-cookie",
        team_outsource="team-sync",
    )
    other_platform = Platform(
        name="Other platform",
        account_username="other@printerval.com",
        session_cookie="other-cookie",
        team_outsource="team-other",
    )
    db_session.add_all([platform, other_platform])
    db_session.flush()
    order = Order(external_order_id="DJ-SYNC-1", platform_id=platform.id, state="WAITING")
    foreign_order = Order(external_order_id="DJ-SYNC-2", platform_id=other_platform.id, state="WAITING")
    db_session.add_all([order, foreign_order])
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}

    first = client.post(
        "/api/sync-jobs",
        json={"type": "status_sync", "order_ids": [str(order.id)]},
        headers=headers,
    )
    second = client.post(
        "/api/sync-jobs",
        json={"type": "status_sync", "order_ids": [str(order.id)]},
        headers=headers,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(dispatched) == 1
    job = db_session.get(SyncJob, uuid.UUID(first.json()["id"]))
    assert job is not None
    assert job.platform_id == platform.id
    assert job.order_ids == [str(order.id)]
    assert job.filters is None

    foreign = client.post(
        "/api/sync-jobs",
        json={"type": "status_sync", "order_ids": [str(foreign_order.id)]},
        headers=headers,
    )
    assert foreign.status_code == 404


def test_sync_job_rejects_more_than_10000_explicit_orders(client, db_session, monkeypatch):
    from app.api.routes import sync_jobs_api

    monkeypatch.setattr(sync_jobs_api, "_dispatch_status_job", lambda job_id: None)
    token = _admin_token(client, db_session)
    platform = Platform(
        name="Sync platform",
        account_username="limit@printerval.com",
        session_cookie="cookie",
        team_outsource="team",
    )
    db_session.add(platform)
    db_session.commit()

    response = client.post(
        "/api/sync-jobs",
        json={"type": "status_sync", "order_ids": [str(uuid.uuid4()) for _ in range(10001)]},
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)},
    )

    assert response.status_code == 422


def test_sync_job_allows_platform_wide_sync_when_order_ids_omitted(client, db_session, monkeypatch):
    from app.api.routes import sync_jobs_api

    monkeypatch.setattr(sync_jobs_api, "_dispatch_status_job", lambda job_id: None)
    token = _admin_token(client, db_session)
    platform = Platform(
        name="Snapshot platform",
        account_username="snapshot@printerval.com",
        session_cookie="cookie",
        team_outsource="team",
    )
    db_session.add(platform)
    db_session.commit()
    headers = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}

    response = client.post("/api/sync-jobs", json={"type": "status_sync"}, headers=headers)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_watchdog_reclaims_only_sync_jobs_without_a_fresh_heartbeat(db_session):
    platform = Platform(
        name="Watchdog platform",
        account_username="watchdog@printerval.com",
        session_cookie="cookie",
        team_outsource="team-watchdog",
    )
    db_session.add(platform)
    db_session.flush()
    stale = SyncJob(
        platform_id=platform.id,
        job_type="status_sync",
        scope_fingerprint="stale-job",
        status="running",
        worker_task_id="dead-worker",
        last_heartbeat_at=datetime.now(UTC) - timedelta(minutes=4),
    )
    fresh = SyncJob(
        platform_id=platform.id,
        job_type="status_sync",
        scope_fingerprint="fresh-job",
        status="running",
        worker_task_id="live-worker",
        last_heartbeat_at=datetime.now(UTC),
    )
    db_session.add_all([stale, fresh])
    db_session.commit()

    assert reclaim_stale_sync_jobs(db_session) == 1

    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert stale.status == "failed"
    assert stale.progress_phase == "failed"
    assert "heartbeat" in stale.error_summary
    assert fresh.status == "running"


def test_support_can_start_a_platform_status_sync_but_a_plain_designer_cannot(client, db_session, monkeypatch):
    """The topbar shows the Đồng bộ button to Support, so the API must accept it (read-only mirror)."""
    from app.api.routes import sync_jobs_api

    monkeypatch.setattr(sync_jobs_api, "_dispatch_status_job", lambda job_id: None)
    platform = Platform(
        name="Support sync platform", account_username="support-sync@printerval.com",
        session_cookie="server-only-cookie", team_outsource="team-support-sync",
    )
    db_session.add(platform)
    db_session.flush()
    for role in ("support", "designer"):
        db_session.add(User(
            username=f"sync_{role}", full_name=role, role=role, password_hash=hash_password("pass123"),
            active=True, platform_id=platform.id,
        ))
    db_session.commit()

    def headers(role):
        token = client.post("/api/login", json={"username": f"sync_{role}", "password": "pass123"}).json()["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}

    ok = client.post("/api/sync-jobs", json={"type": "status_sync"}, headers=headers("support"))
    assert ok.status_code == 202, ok.text
    assert client.post("/api/sync-jobs", json={"type": "status_sync"}, headers=headers("designer")).status_code == 403
