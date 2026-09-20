from datetime import UTC, datetime

from app.adapters.db.models import Assignment, Order, Platform, ResultVersion, User
from app.application.auth import hash_password


def _login(client, db_session, role="admin", username="test_admin"):
    user = db_session.query(User).filter_by(username=username).first()
    if not user:
        user = User(
            username=username,
            role=role,
            full_name=f"Test {role.capitalize()}",
            password_hash=hash_password("s3cret!"),
            active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    resp = client.post("/api/login", json={"username": username, "password": "s3cret!"})
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return user


def test_list_designer_submissions_and_admin_override(client, db_session):
    # 1. Setup Platform & Admin
    platform = Platform(name="Submissions Test Platform", account_username="admin_sub@test.com")
    db_session.add(platform)
    db_session.commit()

    _login(client, db_session, "admin", "admin_sub_user")

    # 2. Setup Designer
    designer = User(username="des_sub_user", role="designer", full_name="Designer Sub", password_hash=hash_password("s3cret!"))
    db_session.add(designer)
    db_session.commit()

    # 3. Setup Order & Assignment & ResultVersions
    order = Order(
        platform_id=platform.id,
        external_order_id="DJ_SUB_9999",
        product_name="Custom Submissions T-Shirt",
        state="QC_PENDING",
        printerval_status="Review",
        note_outsource="gắn link",  # Plain text from Printerval
    )
    db_session.add(order)
    db_session.commit()

    asgn = Assignment(order_id=order.id, designer_id=designer.id, status="assigned")
    db_session.add(asgn)
    db_session.commit()

    rv1 = ResultVersion(
        assignment_id=asgn.id,
        drive_url="https://drive.google.com/file/d/V1_LINK",
        version_marker=1,
        submitted_at=datetime.now(UTC),
        validated=True,
    )
    rv2 = ResultVersion(
        assignment_id=asgn.id,
        drive_url="https://drive.google.com/file/d/V2_LINK",
        version_marker=2,
        submitted_at=datetime.now(UTC),
        validated=True,
    )
    db_session.add_all([rv1, rv2])
    db_session.commit()

    # 4. Test GET /api/orders/designer-submissions
    res = client.get(
        "/api/orders/designer-submissions",
        headers={"X-Platform-ID": str(platform.id)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_items"] == 1
    assert data["total_versions_count"] >= 2

    item = data["items"][0]
    assert item["external_order_id"] == "DJ_SUB_9999"
    assert item["first_drive_url"] == "https://drive.google.com/file/d/V1_LINK"
    assert item["latest_drive_url"] == "https://drive.google.com/file/d/V2_LINK"
    assert len(item["versions"]) == 2
    assert item["current_note_outsource"] == "gắn link"

    # 5. Test search filter
    res_search = client.get(
        "/api/orders/designer-submissions?search=DJ_SUB_9999",
        headers={"X-Platform-ID": str(platform.id)},
    )
    assert res_search.status_code == 200
    assert res_search.json()["total_items"] == 1

    # 6. Test Admin Override Link
    override_res = client.post(
        f"/api/orders/{order.id}/override-submission-link",
        headers={"X-Platform-ID": str(platform.id)},
        json={
            "version_id": str(rv1.id),
            "drive_url": "https://drive.google.com/file/d/OVERRIDDEN_V1_LINK",
            "reason": "Correcting wrong v1 link",
        },
    )
    assert override_res.status_code == 200
    assert override_res.json()["ok"] is True

    # Check updated database record
    db_session.refresh(rv1)
    assert rv1.drive_url == "https://drive.google.com/file/d/OVERRIDDEN_V1_LINK"

    # Re-query list endpoint and verify updated first_drive_url
    res_updated = client.get(
        "/api/orders/designer-submissions",
        headers={"X-Platform-ID": str(platform.id)},
    )
    assert res_updated.status_code == 200
    assert res_updated.json()["items"][0]["first_drive_url"] == "https://drive.google.com/file/d/OVERRIDDEN_V1_LINK"


def test_finance_stats_returns_tasks_and_summary(client, db_session):
    platform = Platform(name="Finance Test Platform", account_username="admin_fin@test.com")
    db_session.add(platform)
    db_session.commit()

    _login(client, db_session, "admin", "admin_fin_user")

    designer = User(username="des_fin_user", role="designer", full_name="Designer Fin", password_hash=hash_password("s3cret!"))
    db_session.add(designer)
    db_session.commit()

    order = Order(
        platform_id=platform.id,
        external_order_id="DJ_FIN_1234",
        product_name="Custom Fin Shirt",
        state="QC_PENDING",
        printerval_status="Review",
        note_outsource="gắn link",
    )
    db_session.add(order)
    db_session.commit()

    asgn = Assignment(order_id=order.id, designer_id=designer.id, status="assigned")
    db_session.add(asgn)
    db_session.commit()

    rv = ResultVersion(
        assignment_id=asgn.id,
        drive_url="https://drive.google.com/file/d/FIN_DRIVE_LINK",
        version_marker=1,
        submitted_at=datetime.now(UTC),
        validated=True,
    )
    db_session.add(rv)
    db_session.commit()

    res = client.get(
        "/api/finance/stats",
        headers={"X-Platform-ID": str(platform.id)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_credited_tasks"] >= 1
    assert len(data["tasks"]) >= 1
    task = data["tasks"][0]
    assert task["external_order_id"] == "DJ_FIN_1234"
    assert task["drive_link"] == "https://drive.google.com/file/d/FIN_DRIVE_LINK"
    assert task["placeholder_filled"] is True
