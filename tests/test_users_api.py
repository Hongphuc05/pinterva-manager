
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Platform, User
from app.api.deps import get_db
from app.api.main import create_app
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
