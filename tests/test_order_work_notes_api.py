from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import Assignment, Order, Platform, User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, db_session, username: str, role: str, platform_id: uuid.UUID) -> User:
    user = User(
        username=username,
        full_name=username,
        role=role,
        platform_id=platform_id if role != "admin" else None,
        password_hash=hash_password("s3cret!"),
        active=True,
    )
    db_session.add(user)
    db_session.commit()
    assert client.post("/api/login", json={"username": username, "password": "s3cret!"}).status_code == 200
    return user


def _seed_order(db_session, platform_id: uuid.UUID) -> Order:
    order = Order(
        platform_id=platform_id,
        external_order_id=f"WORK-NOTE-{uuid.uuid4()}",
        state=OrderState.IN_PROGRESS.value,
        work_domain="standard",
    )
    db_session.add(order)
    db_session.commit()
    return order


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05"
        b"\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_admin_can_append_text_and_private_image_to_order_work_note(client, db_session):
    platform = Platform(id=uuid.uuid4(), name="Work note", account_username="work-note@example.com")
    db_session.add(platform)
    db_session.commit()
    _login(client, db_session, "work-note-admin", "admin", platform.id)
    order = _seed_order(db_session, platform.id)
    original_version = order.version
    headers = {"X-Platform-Id": str(platform.id)}

    created = client.post(
        f"/api/orders/{order.id}/work-notes",
        data={"body": "Đây là ảnh temp", "request_id": "admin-note-1"},
        files={"images": ("temp.png", io.BytesIO(_png_bytes()), "image/png")},
        headers=headers,
    )

    assert created.status_code == 201
    note = created.json()
    assert note["body"] == "Đây là ảnh temp"
    assert len(note["attachments"]) == 1
    assert note["attachments"][0]["url"].startswith("/api/orders/")

    retry = client.post(
        f"/api/orders/{order.id}/work-notes",
        data={"body": "Đây là ảnh temp", "request_id": "admin-note-1"},
        files={"images": ("temp.png", io.BytesIO(_png_bytes()), "image/png")},
        headers=headers,
    )
    assert retry.status_code == 201
    assert retry.json()["id"] == note["id"]

    listed = client.get(f"/api/orders/{order.id}/work-notes", headers=headers)
    assert listed.status_code == 200
    assert [item["body"] for item in listed.json()["notes"]] == ["Đây là ảnh temp"]
    attachment = client.get(note["attachments"][0]["url"], headers=headers)
    assert attachment.status_code == 200
    assert attachment.content == _png_bytes()
    assert attachment.headers["cache-control"] == "private, no-store"
    db_session.refresh(order)
    assert order.version == original_version

    _login(client, db_session, "work-note-image-denied", "designer", platform.id)
    denied = client.get(note["attachments"][0]["url"])
    assert denied.status_code == 404


def test_admin_and_assigned_designer_share_append_only_order_note(client, db_session):
    platform = Platform(id=uuid.uuid4(), name="Work note access", account_username="access@example.com")
    db_session.add(platform)
    db_session.commit()
    _login(client, db_session, "work-note-admin-access", "admin", platform.id)
    order = _seed_order(db_session, platform.id)
    headers = {"X-Platform-Id": str(platform.id)}
    admin_note = client.post(
        f"/api/orders/{order.id}/work-notes",
        data={"body": "Admin đã bổ sung temp", "request_id": "admin-note-access"},
        headers=headers,
    )
    assert admin_note.status_code == 201

    owner = _login(client, db_session, "work-note-owner", "designer", platform.id)
    db_session.add(Assignment(order_id=order.id, designer_id=owner.id, status="approved"))
    db_session.commit()

    visible = client.get(f"/api/orders/{order.id}/work-notes")
    assert visible.status_code == 200
    assert [item["body"] for item in visible.json()["notes"]] == ["Admin đã bổ sung temp"]

    created = client.post(
        f"/api/orders/{order.id}/work-notes",
        data={"body": "Designer báo thiếu temp", "request_id": "designer-note-1"},
    )
    assert created.status_code == 201
    assert created.json()["author_role"] == "designer"
    shared = client.get(f"/api/orders/{order.id}/work-notes")
    assert [item["body"] for item in shared.json()["notes"]] == [
        "Admin đã bổ sung temp",
        "Designer báo thiếu temp",
    ]

    other = _login(client, db_session, "work-note-other", "designer", platform.id)
    assert other.id != owner.id
    denied = client.get(f"/api/orders/{order.id}/work-notes")
    assert denied.status_code == 404


def test_work_note_rejects_non_raster_upload(client, db_session):
    platform = Platform(id=uuid.uuid4(), name="Work note validation", account_username="validation@example.com")
    db_session.add(platform)
    db_session.commit()
    _login(client, db_session, "work-note-validation-admin", "admin", platform.id)
    order = _seed_order(db_session, platform.id)

    response = client.post(
        f"/api/orders/{order.id}/work-notes",
        data={"body": "", "request_id": "bad-image"},
        files={"images": ("attack.svg", io.BytesIO(b"<svg onload=alert(1) />"), "image/svg+xml")},
        headers={"X-Platform-Id": str(platform.id)},
    )
    assert response.status_code == 422
