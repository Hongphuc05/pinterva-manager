import uuid

from app.adapters.db.models import Order, Platform, SyncJob, User
from app.application.auth import hash_password


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


def test_sync_job_rejects_more_than_500_explicit_orders(client, db_session, monkeypatch):
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
        json={"type": "status_sync", "order_ids": [str(uuid.uuid4()) for _ in range(501)]},
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)},
    )

    assert response.status_code == 422
