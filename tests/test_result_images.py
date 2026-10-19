"""Mockup images: required on every Designer submission, pushed to Printerval's Design column once,
before the Review status (Printerval refuses Review without one since 19/10)."""

from __future__ import annotations

import struct
import uuid
import zlib

import pytest

from app.adapters.db.models import (
    Assignment,
    DeadLetter,
    Order,
    Platform,
    ResultImage,
    User,
    WorkflowEvent,
)
from app.application import result_images
from app.application.auth import create_session_token
from app.domain.models import OrderState
from app.workers import assignment_sync_tasks as tasks


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")


def _jpeg(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def test_image_size_reads_png_and_jpeg_headers():
    assert result_images.image_size(_png(1200, 900)) == (1200, 900)
    assert result_images.image_size(_jpeg(640, 480)) == (640, 480)
    assert result_images.image_kind(b"GIF89a....") is None


@pytest.fixture()
def world(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(result_images, "PRIVATE_WORK_NOTE_ASSETS_DIR", tmp_path)
    monkeypatch.setattr(result_images, "RESULT_IMAGES_DIR", tmp_path / "result_images")
    platform = Platform(name="P mock", account_username="m@print.com", session_cookie="x", team_outsource="team",
                        is_active=True)
    db_session.add(platform)
    db_session.flush()

    def user(role):
        u = User(username=f"{role}-{uuid.uuid4().hex[:5]}", full_name=role, role=role, password_hash="x",
                 active=True, platform_id=platform.id)
        db_session.add(u)
        db_session.flush()
        return u

    designer, other, admin = user("designer"), user("designer"), user("admin")
    order = Order(external_order_id="DJ4170001", platform_id=platform.id, state=OrderState.IN_PROGRESS.value,
                  printerval_status="doing", duplicate_check_status="non_duplicate", work_domain="standard")
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.add(Assignment(order_id=order.id, designer_id=other.id, status="cancelled"))
    db_session.commit()
    return type("W", (), {"platform": platform, "designer": designer, "other": other, "admin": admin,
                          "order": order, "session": db_session})


def _h(user):
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def _upload(client, world, user, *files):
    return client.post(f"/api/orders/{world.order.id}/result-images", headers=_h(user),
                       files=[("images", (name, content, "image/png")) for name, content in files])


def test_a_designer_stages_up_to_three_png_or_jpeg_mockups(client, world):
    first = _upload(client, world, world.designer, ("a.png", _png(1200, 1200)), ("b.jpg", _jpeg(800, 600)))
    assert first.status_code == 201
    staged = first.json()["staged"]
    assert [(i["filename"], i["width"], i["height"]) for i in staged] == [("a.png", 1200, 1200), ("b.jpg", 800, 600)]

    too_many = _upload(client, world, world.designer, ("c.png", _png(10, 10)), ("d.png", _png(10, 10)))
    assert too_many.status_code == 422 and "Tối đa 3" in too_many.json()["detail"]
    not_an_image = _upload(client, world, world.designer, ("x.gif", b"GIF89a-not-allowed"))
    assert not_an_image.status_code == 422

    removed = client.delete(f"/api/orders/{world.order.id}/result-images/{staged[0]['id']}", headers=_h(world.designer))
    assert [i["filename"] for i in removed.json()["staged"]] == ["b.jpg"]


def test_a_staged_mockup_is_private_to_its_uploader_until_submitted(client, world):
    [image] = _upload(client, world, world.designer, ("a.png", _png(10, 10))).json()["staged"]
    url = image["url"]
    assert client.get(url, headers=_h(world.designer)).status_code == 200
    assert client.get(url, headers=_h(world.admin)).status_code == 404  # not submitted yet
    stranger = User(username=f"d-{uuid.uuid4().hex[:5]}", full_name="S", role="designer", password_hash="x",
                    active=True, platform_id=world.platform.id)
    world.session.add(stranger)
    world.session.commit()
    assert client.get(url, headers=_h(stranger)).status_code == 404  # not their order at all


def test_submitting_without_a_mockup_is_refused_and_with_one_it_is_attached(client, world, monkeypatch):
    monkeypatch.setattr(tasks.sync_order_review_to_printerval_task, "delay", lambda *_a, **_k: None)
    url = f"/api/orders/{world.order.id}/state"
    refused = client.patch(url, headers=_h(world.designer), json={"state": "Review", "drive_url": "https://x.test/d"})
    assert refused.status_code == 422 and "ảnh mockup" in refused.json()["detail"]
    world.session.refresh(world.order)
    assert world.order.state == OrderState.IN_PROGRESS.value

    [image] = _upload(client, world, world.designer, ("a.png", _png(10, 10))).json()["staged"]
    ok = client.patch(url, headers=_h(world.designer),
                      json={"state": "Review", "drive_url": "https://x.test/d", "image_ids": [image["id"]]})
    assert ok.status_code == 200
    listed = client.get(f"/api/orders/{world.order.id}/result-images", headers=_h(world.admin)).json()
    assert [i["id"] for i in listed["submitted"]] == [image["id"]] and listed["staged"] == []
    assert client.get(image["url"], headers=_h(world.admin)).status_code == 200  # submitted: Admin sees it


def test_another_users_staged_image_cannot_be_submitted(client, world, monkeypatch):
    monkeypatch.setattr(tasks.sync_order_review_to_printerval_task, "delay", lambda *_a, **_k: None)
    foreign = ResultImage(order_id=world.order.id, uploaded_by_id=world.admin.id, storage_key="result_images/f.png",
                          original_filename="f.png", content_type="image/png", byte_size=1, sha256="0" * 64)
    world.session.add(foreign)
    world.session.commit()
    response = client.patch(f"/api/orders/{world.order.id}/state", headers=_h(world.designer),
                            json={"state": "Review", "image_ids": [str(foreign.id)]})
    assert response.status_code == 422


# ----------------------------------------------------------------------------- pushing to Printerval


class _KeepOpen:
    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


class FakePrinterval:
    def __init__(self, *, row=None, status_ok=True, refusal_body=None):
        self.row = row if row is not None else {"id": 4170001, "local_code": "us", "product": {"name": "Jersey"},
                                                 "product_id": 77, "designs": [], "is_custom_design": 0,
                                                 "is_on_demand": 0}
        self.status_ok = status_ok
        self.last_status_error = ""
        self.last_status_refusal = refusal_body or {}
        self.calls: list[tuple] = []

    def __call__(self, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def login(self):
        pass

    def find_order(self, code, statuses=()):
        self.calls.append(("find", statuses))
        return self.row

    def update_order_note_outsource(self, row_id, note):
        self.calls.append(("note", note))
        return True

    def upload_design_file(self, filename, content, content_type):
        self.calls.append(("upload", filename, len(content), content_type))
        return f"https://asset.prtvstatic.com/{filename}"

    def store_design_images(self, job, urls, *, resolution, is_primary):
        self.calls.append(("store", urls, resolution, is_primary))
        return [{"id": 900 + len(self.calls)}]

    def fetch_chat_messages(self, job_id, after_id=0):
        self.calls.append(("chat", job_id))
        return {"messages": [], "chat": {}}

    def update_order_status(self, row_id, status, locale, extra=None):
        self.calls.append(("status", status, locale, extra))
        return self.status_ok


def _staged_and_attached(world, *sizes):
    files = [(f"m{i}.png", _png(w, h)) for i, (w, h) in enumerate(sizes)]
    images = result_images.stage_images(world.session, world.order, world.designer, files)
    result_images.attach_images(world.session, world.order, world.designer, [str(i.id) for i in images])
    world.order.state = OrderState.QC_PENDING.value
    world.session.commit()
    return images


def _run(world, monkeypatch, fake, retries=0, **kwargs):
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _KeepOpen(world.session))
    monkeypatch.setattr(tasks, "PrintervalApiClient", fake)
    task = tasks.sync_order_review_to_printerval_task
    task.push_request(retries=retries, kwargs=kwargs)
    try:
        return task.run(str(world.order.id), "https://drive.test/x", "Review",
                        expected_state=OrderState.QC_PENDING.value, **kwargs)
    finally:
        task.pop_request()


def test_the_review_push_puts_the_mockups_in_the_design_column_first_and_only_once(world, monkeypatch):
    _staged_and_attached(world, (1200, 1200), (800, 600))
    fake = FakePrinterval()

    _run(world, monkeypatch, fake)

    kinds = [c[0] for c in fake.calls]
    assert kinds == ["find", "note", "upload", "store", "upload", "store", "status"]
    stores = [c for c in fake.calls if c[0] == "store"]
    assert stores[0][2:] == ("1200x1200", True) and stores[1][2:] == ("800x600", False)  # first is primary
    assert all(i.pushed_at and i.printerval_image_url for i in world.session.query(ResultImage).all())

    again = FakePrinterval()
    _run(world, monkeypatch, again)
    assert "upload" not in [c[0] for c in again.calls]  # already on Printerval


def test_an_image_already_uploaded_survives_a_failure_on_the_next_one(world, monkeypatch):
    _staged_and_attached(world, (10, 10), (20, 20))
    fake = FakePrinterval()
    real_store = fake.store_design_images
    count = {"n": 0}

    def store_then_fail(job, urls, **kw):
        count["n"] += 1
        if count["n"] == 2:
            raise tasks.ReviewSyncFailed("Printerval chậm", error_class="TRANSIENT_NETWORK")
        return real_store(job, urls, **kw)

    fake.store_design_images = store_then_fail
    monkeypatch.setattr(tasks.sync_order_review_to_printerval_task, "retry",
                        lambda **_k: RuntimeError("retry scheduled"))
    with pytest.raises(RuntimeError):
        _run(world, monkeypatch, fake)
    pushed = [i.pushed_at is not None for i in result_images.submitted_images(world.session, world.order)]
    assert sorted(pushed) == [False, True]
    assert "status" not in [c[0] for c in fake.calls]  # Review never sent without every mockup


def test_a_template_confirmation_request_is_not_retried_and_asks_admin(world, monkeypatch):
    template = {"round": 1, "url": "https://drive.test/temp", "note": "Đổi sang temp Vneck", "status": "pending"}
    fake = FakePrinterval(status_ok=False, refusal_body={"code": "template_confirm",
                                                          "outsource_fix_template": template})
    monkeypatch.setattr(tasks.sync_order_review_to_printerval_task, "retry",
                        lambda **_k: pytest.fail("a template question must not be retried"))
    world.order.state = OrderState.QC_PENDING.value
    world.session.commit()

    _run(world, monkeypatch, fake)

    [alert] = world.session.query(DeadLetter).all()
    assert alert.payload["kind"] == "template_confirm" and alert.payload["fix_template"] == template
    assert alert.error_class == "TEMPLATE_CONFIRM" and alert.resolved_at is None


def test_a_job_that_gives_up_because_the_order_moved_on_after_a_failure_says_so(world, monkeypatch):
    world.order.state = OrderState.REVISION.value  # moved on meanwhile
    world.session.commit()

    _run(world, monkeypatch, FakePrinterval())  # first attempt: nothing failed before, stay quiet
    assert world.session.query(DeadLetter).count() == 0

    _run(world, monkeypatch, FakePrinterval(), retries=1, last_error="HTTP 422: thiếu ảnh")
    [alert] = world.session.query(DeadLetter).all()
    assert "HTTP 422: thiếu ảnh" in alert.payload["error"]


# ----------------------------------------------------------------------------- Admin answers the template question


def _template_alert(world):
    from app.application.printerval_alerts import record_write_failure

    record_write_failure(world.session, world.order, action="đổi trạng thái sang Review", error="cần xác nhận",
                         manual="xác nhận", error_class="TEMPLATE_CONFIRM",
                         extra={"kind": "template_confirm", "target_status": "Review",
                                "fix_template": {"round": 1, "url": "https://drive.test/t", "note": "Vneck"}})
    return world.session.query(DeadLetter).one()


def test_admin_answers_the_template_question_and_the_order_goes_to_review_again(client, world, monkeypatch):
    queued = []
    monkeypatch.setattr(tasks.sync_order_review_to_printerval_task, "delay",
                        lambda *a, **k: queued.append((a, k)))
    world.order.state = OrderState.REVISION.value
    world.session.commit()
    alert = _template_alert(world)

    detail = client.get(f"/api/orders/{world.order.id}", headers=_h(world.admin)).json()["order"]
    assert detail["fix_template_confirm"]["note"] == "Vneck"

    url = f"/api/orders/{world.order.id}/printerval-template-confirm"
    no_reason = client.post(url, headers=_h(world.admin), json={"decision": "disagree", "request_id": "r0"})
    assert no_reason.status_code == 409
    assert client.post(url, headers=_h(world.designer), json={"decision": "agree", "request_id": "r1"}).status_code == 403

    ok = client.post(url, headers=_h(world.admin), json={"decision": "disagree", "note": "Không đổi temp", "request_id": "r2"})
    assert ok.status_code == 200
    world.session.refresh(world.order)
    assert world.order.state == OrderState.QC_PENDING.value
    [(args, kwargs)] = queued
    assert kwargs["template_confirm"] == {"template_confirm": "disagree", "template_confirm_note": "Không đổi temp"}
    assert kwargs["alert_id"] == str(alert.id)
    event = world.session.query(WorkflowEvent).filter_by(order_id=world.order.id).one()
    assert event.evidence["action"] == "CONFIRM_FIX_TEMPLATE" and event.actor_id == world.admin.id


def test_the_answered_push_carries_the_confirmation_and_closes_the_request(world, monkeypatch):
    alert = _template_alert(world)
    world.order.state = OrderState.QC_PENDING.value
    world.session.commit()
    fake = FakePrinterval()

    _run(world, monkeypatch, fake, template_confirm={"template_confirm": "agree"}, alert_id=str(alert.id))

    assert [c for c in fake.calls if c[0] == "status"] == [("status", "review", "us", {"template_confirm": "agree"})]
    world.session.refresh(alert)
    assert alert.resolved_at is not None


def test_leaving_fix_reads_the_chat_first_so_printerval_counts_it_read(world, monkeypatch):
    _staged_and_attached(world, (10, 10))
    world.order.printerval_status = "fix"
    world.session.commit()
    fake = FakePrinterval()

    _run(world, monkeypatch, fake)

    kinds = [c[0] for c in fake.calls]
    assert kinds.index("upload") < kinds.index("chat") < kinds.index("status")
