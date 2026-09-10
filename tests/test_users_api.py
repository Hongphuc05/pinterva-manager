
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import User
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


def test_list_users_as_admin(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_lister")
    resp = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert any(u["username"] == "admin_lister" for u in users)


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


def test_delete_user_as_admin(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_deleter")
    # Create target user to delete
    target = User(
        username="todelete",
        full_name="To Delete",
        role="designer",
        password_hash=hash_password("pass"),
        active=True,
    )
    db_session.add(target)
    db_session.commit()

    resp = client.delete(f"/api/users/{target.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    deleted_user = db_session.get(User, target.id)
    assert deleted_user is None


def test_admin_cannot_self_delete(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_self")
    resp = client.delete(f"/api/users/{admin_user.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 400


def test_update_printerval_designer_option_as_admin(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_pdo")
    target = User(
        username="linh_designer",
        full_name="Linh Designer",
        role="designer",
        password_hash=hash_password("pass"),
        active=True,
    )
    db_session.add(target)
    db_session.commit()

    resp = client.patch(
        f"/api/users/{target.id}/printerval-designer-option",
        json={"printerval_designer_option": "Linh Designer - 2D Prin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["printerval_designer_option"] == "Linh Designer - 2D Prin"

    db_session.refresh(target)
    assert target.printerval_designer_option == "Linh Designer - 2D Prin"


def test_update_printerval_designer_option_clears_with_blank_string(client, db_session):
    admin_user, token = _login(client, db_session, "admin", "admin_pdo2")
    target = User(
        username="hoa_designer",
        full_name="Hoa Designer",
        role="designer",
        password_hash=hash_password("pass"),
        active=True,
        printerval_designer_option="Hoa Designer - 2D Prin",
    )
    db_session.add(target)
    db_session.commit()

    resp = client.patch(
        f"/api/users/{target.id}/printerval-designer-option",
        json={"printerval_designer_option": "  "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["printerval_designer_option"] is None


def test_update_printerval_designer_option_requires_admin(client, db_session):
    designer_user, token = _login(client, db_session, "designer", "designer_pdo")
    resp = client.patch(
        f"/api/users/{designer_user.id}/printerval-designer-option",
        json={"printerval_designer_option": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
