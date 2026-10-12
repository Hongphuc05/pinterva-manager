
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Platform, User
from app.api.deps import get_db
from app.api.main import create_app
from app.api.routes import users_api
from app.application.auth import hash_password


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()



def _login(client, db_session, role="admin", username="testadmin"):
    user = db_session.query(User).filter_by(username=username).one_or_none()
    if user is None:
        user = User(
            username=username,
            full_name=f"Test {role.title()}",
            role=role,
            password_hash=hash_password("pass123"),
            active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

    resp = client.post("/api/login", json={"username": username, "password": "pass123"})
    assert resp.status_code == 200
    token = resp.json().get("access_token")
    return user, token


def _current_platform_id(client, token):
    response = client.get("/api/platforms/current", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    return response.json()["id"]


def test_list_users_as_admin(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_lister")
    resp = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    # This legacy seed administrator predates platform scoping, so it is not in
    # the selected workspace until an admin assigns it through the migration UI.
    assert not any(u["username"] == "admin_lister" for u in users)


def test_create_user_as_admin(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_creator")
    payload = {
        "username": "newdesigner1",
        "password": "designpassword",
        "full_name": "Nguyen Designer",
        "role": "designer",
    }
    resp = client.post("/api/users", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 201
    created = resp.json()
    assert created["username"] == "newdesigner1"
    assert created["role"] == "designer"

    password_response = client.get(
        f"/api/users/{created['id']}/password", headers={"Authorization": f"Bearer {token}"}
    )
    assert password_response.status_code == 200
    assert password_response.json() == {"password": "designpassword", "recoverable": True}


def test_admin_can_create_designer_trello_user(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_trello_creator")
    response = client.post(
        "/api/users",
        json={
            "username": "trello_designer_1",
            "password": "designpassword",
            "full_name": "Trello Designer",
            "role": "designer-trello",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "designer-trello"
    assert response.json()["platform_id"] is not None


def test_admin_can_create_support_user(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_support_creator")
    active_platform_id = _current_platform_id(client, token)
    response = client.post(
        "/api/users",
        json={
            "username": "support_agent_1",
            "password": "supportpassword",
            "full_name": "Support Agent",
            "role": "support",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["role"] == "support"
    assert response.json()["username"] == "support_agent_1"
    assert response.json()["platform_id"] == active_platform_id


def test_admin_created_account_is_bound_to_the_selected_platform(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_admin_creator")
    active_platform_id = _current_platform_id(client, token)

    response = client.post(
        "/api/users",
        json={
            "username": "platform_admin_1",
            "password": "adminpassword",
            "full_name": "Platform Admin",
            "role": "admin",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["platform_id"] == active_platform_id


def test_delete_user_as_admin(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_deleter")
    platform = Platform(name="Delete scope", account_username="delete-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    # Create target user to delete
    target = User(
        username="todelete",
        full_name="To Delete",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add(target)
    db_session.commit()

    resp = client.delete(
        f"/api/users/{target.id}",
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    deleted_user = db_session.get(User, target.id)
    assert deleted_user is None


def test_admin_cannot_self_delete(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_self")
    resp = client.delete(f"/api/users/{admin_user.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


def test_deleting_a_user_with_history_is_refused_with_a_clear_reason_not_a_crash(client, db_session):
    """Regression: used to hit an unhandled FK IntegrityError (500, blank error on the
    frontend) because Assignment/WorkflowEvent etc. reference users.id without cascade —
    on purpose, to never lose audit history. Deleting must be refused cleanly instead."""
    from app.adapters.db.models import Assignment, Order, WorkflowEvent
    from app.domain.models import OrderState

    _, token = _login(client, db_session, "admin", "admin_delete_history")
    platform = Platform(name="History scope", account_username="history-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    target = User(
        username="has_history", full_name="Has History", role="designer",
        password_hash=hash_password("pass"), platform_id=platform.id, active=True,
    )
    db_session.add(target)
    db_session.commit()
    order = Order(external_order_id="HIST-1", platform_id=platform.id, state=OrderState.IN_PROGRESS.value)
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=target.id, status="approved"))
    db_session.add(WorkflowEvent(order_id=order.id, to_state=OrderState.IN_PROGRESS.value, actor_id=target.id))
    db_session.commit()

    resp = client.delete(
        f"/api/users/{target.id}",
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]  # never a blank reason
    assert "khóa" in resp.json()["detail"].lower()

    db_session.expire_all()
    assert db_session.get(User, target.id) is not None  # nothing was deleted


def test_admin_locks_and_unlocks_a_user_instead_of_deleting(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_lock")
    platform = Platform(name="Lock scope", account_username="lock-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    target = User(
        username="lockable", full_name="Lockable", role="designer",
        password_hash=hash_password("pass123"), platform_id=platform.id, active=True,
    )
    db_session.add(target)
    db_session.commit()
    hdr = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}

    res = client.patch(f"/api/users/{target.id}/active", json={"active": False}, headers=hdr)
    assert res.status_code == 200 and res.json()["active"] is False
    db_session.expire_all()
    assert db_session.get(User, target.id).active is False

    # Locked out: cannot log in anymore.
    login_res = client.post("/api/login", json={"username": "lockable", "password": "pass123"})
    assert login_res.status_code == 401

    # Unlock: login works again.
    res = client.patch(f"/api/users/{target.id}/active", json={"active": True}, headers=hdr)
    assert res.status_code == 200 and res.json()["active"] is True
    login_res = client.post("/api/login", json={"username": "lockable", "password": "pass123"})
    assert login_res.status_code == 200


def test_admin_cannot_lock_self_but_lock_endpoint_is_admin_only(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_lock_self")
    res = client.patch(
        f"/api/users/{admin_user.id}/active", json={"active": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400

    _, designer_token = _login(client, db_session, "designer", "designer_no_lock_rights")
    res = client.patch(
        f"/api/users/{admin_user.id}/active", json={"active": False},
        headers={"Authorization": f"Bearer {designer_token}"},
    )
    assert res.status_code == 403


def test_admin_can_reset_another_users_password(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_password_reset")
    platform = Platform(name="Password scope", account_username="password-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    target = User(
        username="linh_designer",
        full_name="Linh Designer",
        role="designer",
        password_hash=hash_password("pass"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add(target)
    db_session.commit()

    resp = client.patch(
        f"/api/users/{target.id}/password",
        json={"password": "new-pass-123"},
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)},
    )
    assert resp.status_code == 200

    db_session.refresh(target)
    login_response = client.post(
        "/api/login", json={"username": target.username, "password": "new-pass-123"}
    )
    assert login_response.status_code == 200

def test_password_endpoints_require_admin(client, db_session):
    designer_user, token = _login(client, db_session, "designer", "designer_password")
    resp = client.get(
        f"/api/users/{designer_user.id}/password", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_designer_can_manage_private_bank_qr_images_and_admin_can_view_them(client, db_session, tmp_path, monkeypatch):
    platform = Platform(name="QR platform", account_username="qr@printerval.com")
    db_session.add(platform)
    db_session.flush()
    designer = User(
        username="qr_designer",
        full_name="QR Designer",
        role="designer",
        password_hash=hash_password("pass123"),
        platform_id=platform.id,
        active=True,
    )
    admin = User(
        username="qr_admin",
        full_name="QR Admin",
        role="admin",
        password_hash=hash_password("pass123"),
        platform_id=platform.id,
        active=True,
    )
    db_session.add_all([designer, admin])
    db_session.commit()
    monkeypatch.setattr(users_api, "BANK_QR_ASSETS_DIR", tmp_path / "bank_qr")

    designer_token = client.post("/api/login", json={"username": "qr_designer", "password": "pass123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {designer_token}"}
    png = b"\x89PNG\r\n\x1a\nqr-image"

    assert client.get("/api/users/me/bank-qr", headers=headers).json() == {"images": []}
    created = []
    for index in range(3):
        response = client.post(
            "/api/users/me/bank-qr",
            headers=headers,
            files={"file": (f"qr-{index}.png", png + bytes([index]), "image/png")},
        )
        assert response.status_code == 201
        created.append(response.json())

    limit_response = client.post(
        "/api/users/me/bank-qr",
        headers=headers,
        files={"file": ("qr-extra.png", png, "image/png")},
    )
    assert limit_response.status_code == 409

    replacement = client.post(
        f"/api/users/me/bank-qr?replace_image_id={created[0]['id']}",
        headers=headers,
        files={"file": ("new-qr.webp", b"RIFF0000WEBPnew", "image/webp")},
    )
    assert replacement.status_code == 201
    assert replacement.json()["id"] == created[0]["id"]
    assert replacement.json()["filename"] == "new-qr.webp"

    admin_token = client.post("/api/login", json={"username": "qr_admin", "password": "pass123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Platform-Id": str(platform.id)}
    listing = client.get(f"/api/users/{designer.id}/bank-qr", headers=admin_headers)
    assert listing.status_code == 200
    assert len(listing.json()["images"]) == 3

    image_response = client.get(listing.json()["images"][0]["url"], headers=admin_headers)
    assert image_response.status_code == 200
    assert image_response.headers["cache-control"] == "private, no-store"

    deleted = client.delete(f"/api/users/me/bank-qr/{created[1]['id']}", headers=headers)
    assert deleted.status_code == 204
    assert len(client.get("/api/users/me/bank-qr", headers=headers).json()["images"]) == 2


def test_users_are_scoped_to_the_admin_selected_platform(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_user_scope")
    first = Platform(name="First", account_username="first@printerval.com")
    second = Platform(name="Second", account_username="second@printerval.com")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all([
        User(username="first_support", full_name="First Support", role="support", password_hash=hash_password("pass"), platform_id=first.id),
        User(username="second_support", full_name="Second Support", role="support", password_hash=hash_password("pass"), platform_id=second.id),
    ])
    db_session.commit()

    response = client.get(
        "/api/users",
        headers={"Authorization": f"Bearer {token}", "X-Platform-Id": str(first.id)},
    )

    assert response.status_code == 200
    assert [user["username"] for user in response.json()] == ["first_support"]


def test_admin_can_bind_a_legacy_operational_user_to_current_platform(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_legacy_bind")
    platform = Platform(name="Scoped", account_username="scoped@printerval.com")
    legacy_user = User(
        username="legacy_support",
        full_name="Legacy Support",
        role="support",
        password_hash=hash_password("pass"),
    )
    db_session.add_all([platform, legacy_user])
    db_session.commit()

    headers = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}
    migration_queue = client.get("/api/users/unassigned", headers=headers)
    assert migration_queue.status_code == 200
    assert "legacy_support" in [user["username"] for user in migration_queue.json()]

    response = client.patch(f"/api/users/{legacy_user.id}/platform", headers=headers)
    assert response.status_code == 200
    assert response.json()["platform_id"] == str(platform.id)


def test_support_cannot_switch_workspace_with_a_browser_header(client, db_session):
    first = Platform(name="First", account_username="first@printerval.com")
    second = Platform(name="Second", account_username="second@printerval.com")
    db_session.add_all([first, second])
    db_session.flush()
    support = User(
        username="scoped_support",
        full_name="Scoped Support",
        role="support",
        password_hash=hash_password("pass123"),
        platform_id=first.id,
    )
    db_session.add(support)
    db_session.commit()

    _, token = _login(client, db_session, "support", "scoped_support")
    headers = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(second.id)}

    current = client.get("/api/platforms/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["id"] == str(first.id)
    assert client.get("/api/platforms", headers=headers).status_code == 403


def test_force_delete_cascades_everything_the_user_owns(client, db_session):
    """The explicit "Xóa tất cả" path: Admin already saw the 409 and chose to nuke it anyway."""
    from app.adapters.db.models import Assignment, Order, WorkflowEvent
    from app.domain.models import OrderState

    _, token = _login(client, db_session, "admin", "admin_force_delete")
    platform = Platform(name="Force scope", account_username="force-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    target = User(
        username="force_me", full_name="Force Me", role="designer",
        password_hash=hash_password("pass"), platform_id=platform.id, active=True,
    )
    db_session.add(target)
    db_session.commit()
    order = Order(external_order_id="FORCE-1", platform_id=platform.id, state=OrderState.IN_PROGRESS.value)
    db_session.add(order)
    db_session.flush()
    assignment = Assignment(order_id=order.id, designer_id=target.id, status="approved")
    event = WorkflowEvent(order_id=order.id, to_state=OrderState.IN_PROGRESS.value, actor_id=target.id)
    db_session.add_all([assignment, event])
    db_session.commit()
    assignment_id, event_id, order_id = assignment.id, event.id, order.id

    hdr = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}
    resp = client.delete(f"/api/users/{target.id}?force=true", headers=hdr)
    assert resp.status_code == 200

    db_session.expire_all()
    assert db_session.get(User, target.id) is None
    assert db_session.get(Assignment, assignment_id) is None  # cascaded: it's the designer's own record
    # The Order itself survives — it's not the deleted user's own record, and the event
    # that references them keeps existing (SET NULL), so the order's audit trail is intact.
    assert db_session.get(Order, order_id) is not None
    kept_event = db_session.get(WorkflowEvent, event_id)
    assert kept_event is not None and kept_event.actor_id is None


def test_locked_accounts_are_hidden_from_the_list_by_default(client, db_session):
    _, token = _login(client, db_session, "admin", "admin_hide_locked")
    platform = Platform(name="Hide scope", account_username="hide-scope@printerval.com")
    db_session.add(platform)
    db_session.commit()
    target = User(
        username="to_be_hidden", full_name="To Be Hidden", role="designer",
        password_hash=hash_password("pass"), platform_id=platform.id, active=True,
    )
    db_session.add(target)
    db_session.commit()
    hdr = {"Authorization": f"Bearer {token}", "X-Platform-Id": str(platform.id)}

    assert client.patch(f"/api/users/{target.id}/active", json={"active": False}, headers=hdr).status_code == 200

    names = [u["username"] for u in client.get("/api/users", headers=hdr).json()]
    assert "to_be_hidden" not in names

    names_with_locked = [u["username"] for u in client.get("/api/users?include_locked=true", headers=hdr).json()]
    assert "to_be_hidden" in names_with_locked


def test_two_platforms_may_reuse_the_same_username_and_login_still_resolves_correctly(client, db_session):
    _, admin_token = _login(client, db_session, "admin", "admin_dup_username")
    platform_a = Platform(name="Dup A", account_username="dup-a@printerval.com")
    platform_b = Platform(name="Dup B", account_username="dup-b@printerval.com")
    db_session.add_all([platform_a, platform_b])
    db_session.commit()
    hdr_a = {"Authorization": f"Bearer {admin_token}", "X-Platform-Id": str(platform_a.id)}
    hdr_b = {"Authorization": f"Bearer {admin_token}", "X-Platform-Id": str(platform_b.id)}

    body = {"username": "support1", "full_name": "Support One", "password": "passA123", "role": "support"}
    res_a = client.post("/api/users", json=body, headers=hdr_a)
    assert res_a.status_code == 201, res_a.text
    # Same username, different platform, different password: not a conflict.
    res_b = client.post("/api/users", json={**body, "password": "passB123"}, headers=hdr_b)
    assert res_b.status_code == 201, res_b.text
    # Same username, SAME platform: still refused.
    assert client.post("/api/users", json={**body, "password": "whatever1"}, headers=hdr_a).status_code == 400

    # Login (no platform selector) must resolve to the matching one by password.
    login_a = client.post("/api/login", json={"username": "support1", "password": "passA123"})
    login_b = client.post("/api/login", json={"username": "support1", "password": "passB123"})
    assert login_a.status_code == 200 and login_a.json()["id"] == res_a.json()["id"]
    assert login_b.status_code == 200 and login_b.json()["id"] == res_b.json()["id"]
    assert client.post("/api/login", json={"username": "support1", "password": "wrong"}).status_code == 401
