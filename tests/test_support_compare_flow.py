"""Support duplicate-check flow: /check count, /handle, /help and the selected-pair Telegram step."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.adapters.db.models import (
    Order,
    Platform,
    SupportCompareCandidate,
    SupportCompareItem,
    SupportCompareRun,
    TelegramActionLog,
    User,
)
from app.application.auth import hash_password
from app.application.support_compare import (
    count_handleable_orders,
    count_support_unchecked_orders,
    execute_support_duplicate_decision,
    notify_pending_duplicate_candidates,
)
from app.domain.models import OrderState

CHAT_ID = "554433"


@pytest.fixture()
def setup(db_session):
    platform = Platform(name="Plat flow", account_username="flow@print.com", is_active=True)
    db_session.add(platform)
    db_session.flush()
    support = User(
        username="support-flow", full_name="Support Flow", role="support",
        password_hash=hash_password("pass"), telegram_chat_id=CHAT_ID,
        active=True, platform_id=platform.id,
    )
    run = SupportCompareRun(
        id=uuid.uuid4(), source_kind="support_unchecked", platform_id=platform.id,
        model_version="m", embedding_dim=3, classifier_version="c", started_at=datetime.now(UTC),
    )
    db_session.add_all([support, run])
    db_session.commit()
    return SimpleNamespace(platform=platform, support=support, run=run)


def _order(db_session, ctx, code: str, state: str = OrderState.WAITING.value) -> Order:
    order = Order(
        external_order_id=code, platform_id=ctx.platform.id, state=state,
        duplicate_check_status="uncheck", work_domain="standard",
    )
    db_session.add(order)
    db_session.commit()
    return order


def _item(db_session, ctx, order: Order, review_status: str | None, *, is_duplicate=False):
    now = datetime.now(UTC)
    item = SupportCompareItem(
        id=uuid.uuid4(), run_id=ctx.run.id, platform_id=ctx.platform.id, order_id=order.id,
        external_order_id=order.external_order_id, image_url="https://example.test/new.png",
        image_url_sha256=uuid.uuid4().hex + uuid.uuid4().hex, model_version="m",
        processing_status="completed", is_duplicate=is_duplicate, review_status=review_status,
        created_at=now, updated_at=now,
    )
    db_session.add(item)
    db_session.commit()
    return item


def _candidate(db_session, item: SupportCompareItem, rank: int = 1) -> SupportCompareCandidate:
    asset_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.image_assets "
            "(id, source_system, url_sha256, raw_url, url, fetch_status) "
            "VALUES (:id, 'test', :sha, :url, :url, 'embedded')"
        ),
        {"id": asset_id, "sha": uuid.uuid4().hex + uuid.uuid4().hex, "url": "https://example.test/old.png"},
    )
    candidate = SupportCompareCandidate(
        id=uuid.uuid4(), comparison_item_id=item.id, historical_asset_id=asset_id,
        matched_external_order_id=f"OLD-{rank}", matched_image_url="https://example.test/old.png",
        rank=rank, visual_similarity=0.9, classification="TRUNG", confidence=0.9,
        classifier_version="c", created_at=datetime.now(UTC),
    )
    db_session.add(candidate)
    db_session.commit()
    return candidate


def _webhook(client: TestClient, payload: dict):
    with (
        patch(
            "app.api.routes.telegram_api.get_settings",
            return_value=SimpleNamespace(support_compare_enabled=True, telegram_webhook_secret=None),
        ),
        patch("app.api.routes.telegram_api.send_message", return_value={"message_id": 901}) as send,
        patch("app.api.routes.telegram_api.clear_message_keyboard"),
        patch("app.api.routes.telegram_api.delete_messages"),
    ):
        assert client.post("/api/telegram/webhook", json=payload).status_code == 200
    return send


def _text(text: str) -> dict:
    return {"message": {"chat": {"id": int(CHAT_ID)}, "from": {"id": int(CHAT_ID)}, "text": text}}


def test_check_counts_only_orders_never_compared(db_session, setup):
    fresh = _order(db_session, setup, "DJ-FRESH")
    compared = _order(db_session, setup, "DJ-COMPARED")
    _item(db_session, setup, compared, "no_match")
    failed = _order(db_session, setup, "DJ-FAILED")
    failed_item = _item(db_session, setup, failed, None)
    failed_item.processing_status = "failed"
    db_session.commit()

    assert fresh and count_support_unchecked_orders(db_session, platform_id=setup.platform.id) == 2


def test_handleable_orders_are_no_match_and_ai_wrong_without_open_review(db_session, setup):
    no_match = _order(db_session, setup, "DJ-NO-MATCH")
    _item(db_session, setup, no_match, "no_match")
    ai_wrong = _order(db_session, setup, "DJ-AI-WRONG")
    _item(db_session, setup, ai_wrong, "ai_wrong", is_duplicate=True)
    pending = _order(db_session, setup, "DJ-PENDING")
    _item(db_session, setup, pending, "pending_review", is_duplicate=True)
    selected = _order(db_session, setup, "DJ-SELECTED")
    _item(db_session, setup, selected, "selected_duplicate", is_duplicate=True)
    _order(db_session, setup, "DJ-NEVER-COMPARED")

    assert count_handleable_orders(db_session, platform_id=setup.platform.id) == 2


def test_handle_command_reports_count_then_moves_orders_after_yes(client, db_session, setup):
    no_match = _order(db_session, setup, "DJ-H-NO-MATCH")
    _item(db_session, setup, no_match, "no_match")
    pending = _order(db_session, setup, "DJ-H-PENDING")
    _item(db_session, setup, pending, "pending_review", is_duplicate=True)
    untouched = _order(db_session, setup, "DJ-H-FRESH")

    send = _webhook(client, _text("/handle"))
    prompt = next(call for call in send.call_args_list if "reply_markup" in call.kwargs)
    assert "<b>1</b>" in prompt.args[1]
    yes_data = prompt.kwargs["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert yes_data.startswith("schandle_yes:")

    send = _webhook(client, {"callback_query": {"id": "cb", "data": yes_data, "from": {"id": int(CHAT_ID)}}})
    assert "<b>1</b>" in send.call_args.args[1]

    for order in (no_match, pending, untouched):
        db_session.refresh(order)
    assert no_match.duplicate_check_status == "non_duplicate"
    assert pending.duplicate_check_status == "uncheck"
    assert untouched.duplicate_check_status == "uncheck"


def test_handle_and_check_prompts_replace_each_other(client, db_session, setup):
    _order(db_session, setup, "DJ-R-FRESH")
    no_match = _order(db_session, setup, "DJ-R-NOMATCH")
    _item(db_session, setup, no_match, "no_match")

    _webhook(client, _text("/check"))
    _webhook(client, _text("/handle"))

    statuses = sorted(a.status for a in db_session.query(TelegramActionLog).all())
    assert statuses == ["pending", "pending", "superseded", "superseded"]


def test_help_lists_the_support_commands(client, db_session, setup):
    send = _webhook(client, _text("/help"))
    text = send.call_args.args[1]
    assert "/check" in text and "/handle" in text and "/help" in text


def test_only_the_candidate_selected_on_localhost_is_sent(db_session, setup):
    order = _order(db_session, setup, "DJ-SEL")
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    first, second = _candidate(db_session, item, 1), _candidate(db_session, item, 2)

    with patch("app.application.support_compare.send_media_group") as media, \
            patch("app.application.support_compare.send_message", return_value={"message_id": 5}) as msg:
        assert notify_pending_duplicate_candidates(db_session) == 0  # nothing selected yet
        media.assert_not_called()

        item.review_status, item.selected_candidate_id = "selected_duplicate", second.id
        item.reviewed_at = datetime.now(UTC)
        db_session.commit()
        media.return_value = [{}]
        assert notify_pending_duplicate_candidates(db_session) == 1

    db_session.refresh(first), db_session.refresh(second)
    assert second.telegram_notified_at is not None and first.telegram_notified_at is None
    assert "DJ-SEL" in msg.call_args.args[1] and "OLD-2" in msg.call_args.args[1]
    sent_media = media.call_args.args[1]
    assert sent_media[1]["media"] == second.matched_image_url


def test_decision_requires_the_localhost_selection(db_session, setup):
    order = _order(db_session, setup, "DJ-DEC")
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    candidate = _candidate(db_session, item)
    action = TelegramActionLog(
        order_id=order.id, action_type="SUPPORT_COMPARE_CONFIRM_DUPLICATE", callback_token="tok",
        payload={"candidate_id": str(candidate.id), "chat_id": CHAT_ID}, expires_at=None,
    )
    db_session.add(action)
    db_session.commit()

    with pytest.raises(ValueError, match="chưa được Support chọn"):
        execute_support_duplicate_decision(
            db_session, actor=setup.support, action_log=action, decision_status="duplicate"
        )

    item.review_status, item.selected_candidate_id = "selected_duplicate", candidate.id
    db_session.commit()
    execute_support_duplicate_decision(
        db_session, actor=setup.support, action_log=action, decision_status="duplicate"
    )
    db_session.refresh(order)
    assert order.duplicate_check_status == "duplicate"


def _login_headers(client, user: User) -> dict[str, str]:
    from app.application.auth import create_session_token

    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}"}


def test_web_check_queues_a_job_for_the_never_compared_orders(client, db_session, setup):
    _order(db_session, setup, "DJ-WEB-1")
    _order(db_session, setup, "DJ-WEB-2")
    headers = _login_headers(client, setup.support)
    with patch(
        "app.api.routes.support_compare_api.get_settings",
        return_value=SimpleNamespace(support_compare_enabled=True),
    ):
        status = client.get("/api/support-compare/status", headers=headers)
        assert status.status_code == 200
        assert status.json() == {"enabled": True, "new_orders": 2, "handleable_orders": 0}

        res = client.post("/api/support-compare/check", headers=headers)
        assert res.status_code == 200
        assert res.json()["requested_count"] == 2


def _bearer(user: User) -> dict[str, str]:
    """Session of a Support who also opened the hidden review area (password set directly in the DB)."""
    from app.application import support_review_access as access
    from app.application.auth import create_session_token
    from tests.conftest import TEST_DATABASE_URL  # noqa: F401 (same DB as the fixtures)

    session = _bearer.session  # set by the autouse fixture below
    record = access.get_access(session, user.platform_id)
    token = (
        access.issue_token(user, record)
        if record
        else access.set_initial_password(session, user=user, platform_id=user.platform_id, password="secret1")
    )
    session.commit()
    return {"Authorization": f"Bearer {create_session_token(str(user.id), user.role)}", "X-Review-Token": token}


@pytest.fixture(autouse=True)
def _bearer_session(db_session):
    _bearer.session = db_session


def test_web_review_selects_a_candidate_or_marks_the_model_wrong(client, db_session, setup):
    from app.adapters.db.models import SupportCompareJob

    picked = _order(db_session, setup, "DJ-REV-PICK")
    picked_item = _item(db_session, setup, picked, "pending_review", is_duplicate=True)
    cand_a, cand_b = _candidate(db_session, picked_item, 1), _candidate(db_session, picked_item, 2)
    wrong = _order(db_session, setup, "DJ-REV-WRONG")
    wrong_item = _item(db_session, setup, wrong, "pending_review", is_duplicate=True)
    _candidate(db_session, wrong_item, 1)
    quiet = _order(db_session, setup, "DJ-REV-QUIET")
    _item(db_session, setup, quiet, "no_match")
    job = SupportCompareJob(
        platform_id=setup.platform.id, chat_id=CHAT_ID, status="completed", run_id=setup.run.id
    )
    db_session.add(job)
    db_session.commit()
    headers = _bearer(setup.support)

    data = client.get(f"/api/support-review/jobs/{job.id}", headers=headers).json()
    by_code = {i["order_code"]: i for i in data["items"]}
    assert set(by_code) == {"DJ-REV-PICK", "DJ-REV-WRONG", "DJ-REV-QUIET"}
    assert [c["order_code"] for c in by_code["DJ-REV-PICK"]["candidates"]] == ["OLD-1", "OLD-2"]

    res = client.post(
        f"/api/support-review/items/{picked_item.id}/select", json={"candidate_id": str(cand_b.id)}, headers=headers
    )
    assert res.status_code == 200
    assert client.post(f"/api/support-review/items/{wrong_item.id}/reject", headers=headers).status_code == 200
    db_session.expire_all()
    assert (picked_item.review_status, picked_item.selected_candidate_id) == ("selected_duplicate", cand_b.id)
    assert wrong_item.review_status == "ai_wrong"

    # The choice can be changed until the pair has gone to Telegram, then it is frozen.
    assert client.post(
        f"/api/support-review/items/{picked_item.id}/select", json={"candidate_id": str(cand_a.id)}, headers=headers
    ).status_code == 200
    cand_a.telegram_notified_at = datetime.now(UTC)
    db_session.commit()
    assert client.post(f"/api/support-review/items/{picked_item.id}/reject", headers=headers).status_code == 409

    # A candidate of another item is refused, and no-match items are not reviewable.
    assert client.post(
        f"/api/support-review/items/{wrong_item.id}/select", json={"candidate_id": str(cand_a.id)}, headers=headers
    ).status_code == 400
    quiet_item_id = by_code["DJ-REV-QUIET"]["id"]
    assert client.post(f"/api/support-review/items/{quiet_item_id}/reject", headers=headers).status_code == 409


def test_web_review_requires_a_support_session(client, db_session, setup):
    assert client.get("/api/support-review/jobs").status_code == 401
    designer = User(
        username="des-review", full_name="D", role="designer", password_hash=hash_password("pass"),
        active=True, platform_id=setup.platform.id,
    )
    db_session.add(designer)
    db_session.commit()
    assert client.get("/api/support-review/jobs", headers=_bearer(designer)).status_code == 403
    assert client.get("/api/support-worker/queue", headers=_bearer(designer)).status_code == 403


def _seed_pool_job(db_session, code: str, config=None) -> uuid.UUID:
    job_id = uuid.uuid4()
    db_session.execute(
        text(
            "INSERT INTO support_compare_image.historical_jobs "
            "(id, source_system, source_job_id, external_order_id, status, team_outsource, job_type, product_name, custom_config) "
            "VALUES (:id, 'printerval', :code, :code, 'done', 'team', 'all', 'Áo', CAST(:cfg AS jsonb))"
        ),
        {"id": job_id, "code": code, "cfg": json.dumps(config) if config else None},
    )
    db_session.commit()
    return job_id


def _find_row(job_id: int, configurations: dict | None) -> dict:
    sku = {"configurations": json.dumps(configurations)} if configurations else {}
    return {"id": job_id, "meta_data": json.dumps({"product_skus": {"1": sku}})}


class _FakeClient:
    def __init__(self, pages: dict[tuple[str, int], list[dict]]):
        self.pages = pages

    def discover_page(self, *, status, page_size, page_id):
        return SimpleNamespace(orders=self.pages.get((status, page_id), []))


def test_backfill_stores_the_custom_configuration_of_pool_jobs(db_session):
    from app.application.historical_config_backfill import backfill

    with_cfg = _seed_pool_job(db_session, "DJ111")
    without_cfg = _seed_pool_job(db_session, "DJ222")
    untouched = _seed_pool_job(db_session, "DJ999")
    client = _FakeClient({
        ("done", 0): [_find_row(111, {"Color Choice": "Black", "Name": "Anh"}), _find_row(222, None)],
        ("fix", 0): [_find_row(555, {"x": "y"})],  # not in the pool: ignored
    })

    dry = backfill(db_session, client, dry_run=True, sleep=lambda _: None, progress=lambda _: None)
    assert dry["rows"] == 3 and dry["with_config"] == 2
    assert db_session.execute(text("SELECT count(*) FROM support_compare_image.historical_jobs WHERE custom_config_synced_at IS NOT NULL")).scalar_one() == 0

    stats = backfill(db_session, client, sleep=lambda _: None, progress=lambda _: None)
    assert stats == {"pages": 2, "rows": 3, "with_config": 2}
    rows = {
        r.external_order_id: r
        for r in db_session.execute(text("SELECT external_order_id, custom_config, custom_config_synced_at FROM support_compare_image.historical_jobs"))
    }
    entries = {e["key"].lower(): e["value"] for e in rows["DJ111"].custom_config["original"]}
    assert entries == {"color choice": "Black", "name": "Anh"}
    assert rows["DJ111"].custom_config_synced_at is not None
    assert rows["DJ222"].custom_config is None and rows["DJ222"].custom_config_synced_at is not None  # looked up, none
    assert rows["DJ999"].custom_config_synced_at is None  # never returned by Printerval
    assert with_cfg and without_cfg and untouched


def test_selected_pair_message_includes_both_custom_configurations(db_session, setup):
    order = _order(db_session, setup, "DJ-CFG-NEW")
    order.custom_config = {
        "original": [{"key": "Name", "value": "Bố <3"}],
        "translated_vn": [{"key": "Tên", "value": "Bố <3"}, {"key": "extra_discount_ab", "value": "0"}, {"key": "url_xem_trước", "value": "/customize/x.jpg"}],
    }
    db_session.commit()
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    candidate = _candidate(db_session, item, 1)
    candidate.historical_job_id = _seed_pool_job(
        db_session, "OLD-1", {"original": [{"key": "Color", "value": "Black"}], "translated_vn": []}
    )
    item.review_status, item.selected_candidate_id, item.reviewed_at = "selected_duplicate", candidate.id, datetime.now(UTC)
    db_session.commit()

    with patch("app.application.support_compare.send_media_group", return_value=[{}]) as media, \
            patch("app.application.support_compare.send_message", return_value={"message_id": 7}) as msg:
        assert notify_pending_duplicate_candidates(db_session) == 1

    # One message: the album carries both order captions and both configurations.
    photos = media.call_args.args[1]
    caption = photos[0]["caption"]
    assert "caption" not in photos[1]
    assert "DJ-CFG-NEW" in caption and "OLD-1" in caption
    assert "<b>Tên</b>: Bố &lt;3" in caption  # Vietnamese preferred, HTML-escaped
    assert "<b>Color</b>: Black" in caption  # falls back to the original entries
    assert "extra_discount" not in caption and "url_xem" not in caption
    assert len(caption) <= 1024
    assert len(msg.call_args_list) == 1  # only the confirmation prompt is a separate message
    # the confirmation buttons still come last
    assert "reply_markup" in msg.call_args_list[-1].kwargs


def test_album_caption_stays_under_the_telegram_limit_with_long_configurations(db_session, setup):
    from app.application.support_compare import CAPTION_LIMIT, _combined_caption

    order = _order(db_session, setup, "DJ-LONG")
    order.custom_config = {"original": [{"key": f"Option {n}", "value": "x" * 120} for n in range(30)], "translated_vn": []}
    db_session.commit()
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    candidate = _candidate(db_session, item, 1)

    caption = _combined_caption(db_session, item, candidate)
    assert len(caption) <= CAPTION_LIMIT
    assert "Cấu hình đơn mới DJ-LONG" in caption and "…" in caption


def _notify_selected_pair(db_session, setup, code: str):
    order = _order(db_session, setup, code)
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    candidate = _candidate(db_session, item, 1)
    item.review_status, item.selected_candidate_id, item.reviewed_at = "selected_duplicate", candidate.id, datetime.now(UTC)
    db_session.commit()
    with patch("app.application.support_compare.send_media_group", return_value=[{"message_id": 11}, {"message_id": 12}]), \
            patch("app.application.support_compare.send_message", return_value={"message_id": 13}):
        assert notify_pending_duplicate_candidates(db_session) == 1
    return order, {
        a.action_type: a.callback_token
        for a in db_session.query(TelegramActionLog).filter(TelegramActionLog.order_id == order.id)
    }


def _press(client, data: str, *, delete_ok: bool):
    with (
        patch("app.api.routes.telegram_api.get_settings", return_value=SimpleNamespace(support_compare_enabled=True, telegram_webhook_secret=None)),
        patch("app.api.routes.telegram_api.send_message", return_value={"message_id": 99}) as send,
        patch("app.api.routes.telegram_api.clear_message_keyboard") as clear,
        patch("app.api.routes.telegram_api.delete_messages", return_value=delete_ok) as delete,
        patch("app.api.routes.telegram_api.answer_callback_query") as answer,
    ):
        client.post("/api/telegram/webhook", json={"callback_query": {"id": "cb1", "data": data, "from": {"id": int(CHAT_ID)}}})
    return send, clear, delete, answer


@pytest.mark.parametrize(("button", "status", "toast"), [
    ("SUPPORT_COMPARE_CONFIRM_DUPLICATE", "duplicate", "Đã xác nhận trùng"),
    ("SUPPORT_COMPARE_REJECT_DUPLICATE", "non_duplicate", "Đã đưa vào Không trùng lặp"),
])
def test_deciding_a_pair_deletes_its_messages_from_the_chat(client, db_session, setup, button, status, toast):
    order, tokens = _notify_selected_pair(db_session, setup, f"DJ-DEL-{status}")
    prefix = "scdup_yes" if "CONFIRM" in button else "scdup_no"

    send, clear, delete, answer = _press(client, f"{prefix}:{tokens[button]}", delete_ok=True)

    delete.assert_called_once_with(CHAT_ID, [11, 12, 13])  # album + prompt
    assert toast in answer.call_args.args[1] and order.external_order_id in answer.call_args.args[1]
    send.assert_not_called()  # nothing is left in the chat
    clear.assert_not_called()
    db_session.refresh(order)
    assert order.duplicate_check_status == status


def test_when_the_messages_cannot_be_deleted_the_prompt_is_closed_and_the_result_is_sent(client, db_session, setup):
    order, tokens = _notify_selected_pair(db_session, setup, "DJ-DEL-FALLBACK")

    send, clear, delete, answer = _press(client, f"scdup_yes:{tokens['SUPPORT_COMPARE_CONFIRM_DUPLICATE']}", delete_ok=False)

    clear.assert_called_once_with(CHAT_ID, 13)
    assert order.external_order_id in send.call_args.args[1]
    answer.assert_not_called()


def test_pairs_sent_before_ids_were_stored_still_lose_their_album_and_configuration_message(client, db_session, setup):
    order, tokens = _notify_selected_pair(db_session, setup, "DJ-LEGACY")
    for action in db_session.query(TelegramActionLog).filter(TelegramActionLog.order_id == order.id):
        action.payload = {k: v for k, v in action.payload.items() if k != "message_ids"}
        action.payload = {**action.payload, "message_id": 20}  # legacy: only the prompt id was stored
    other = TelegramActionLog(  # the previous pair's prompt (4 messages earlier) must not be touched
        order_id=order.id, action_type="SUPPORT_COMPARE_CONFIRM_DUPLICATE", callback_token="prev",
        payload={"chat_id": CHAT_ID, "message_id": 18}, status="executed",
    )
    db_session.add(other)
    db_session.commit()

    _, _, delete, _ = _press(client, f"scdup_yes:{tokens['SUPPORT_COMPARE_CONFIRM_DUPLICATE']}", delete_ok=True)

    delete.assert_called_once_with(CHAT_ID, [17, 19, 20])


def test_decision_still_works_when_the_order_version_changed_after_the_notification(client, db_session, setup):
    order, tokens = _notify_selected_pair(db_session, setup, "DJ-VERSION-DRIFT")
    order.product_name = "changed by the status sync"  # bumps Order.version after the pair was sent
    db_session.commit()
    db_session.refresh(order)
    assert order.version > 1

    send, _, delete, answer = _press(client, f"scdup_yes:{tokens['SUPPORT_COMPARE_CONFIRM_DUPLICATE']}", delete_ok=True)

    db_session.refresh(order)
    assert order.duplicate_check_status == "duplicate"
    delete.assert_called_once()
    send.assert_not_called()


def test_pressing_a_used_button_shows_a_toast_instead_of_a_chat_message(client, db_session, setup):
    _, tokens = _notify_selected_pair(db_session, setup, "DJ-STALE-BTN")
    data = f"scdup_no:{tokens['SUPPORT_COMPARE_REJECT_DUPLICATE']}"
    _press(client, data, delete_ok=True)

    send, _, delete, answer = _press(client, data, delete_ok=True)  # double tap / Telegram retry

    send.assert_not_called()
    delete.assert_not_called()
    assert "đã được xử lý" in answer.call_args.args[1]


def test_a_decision_interrupted_after_the_order_changed_is_finished_by_the_next_click(client, db_session, setup):
    order, tokens = _notify_selected_pair(db_session, setup, "DJ-INTERRUPTED")
    # first click changed the order, then the process was killed before the action/candidate were closed
    order.duplicate_check_status = "duplicate"
    db_session.commit()

    send, _, delete, answer = _press(client, f"scdup_yes:{tokens['SUPPORT_COMPARE_CONFIRM_DUPLICATE']}", delete_ok=True)

    delete.assert_called_once()
    assert "Đã xác nhận trùng" in answer.call_args.args[1]
    send.assert_not_called()
    statuses = {a.action_type: a.status for a in db_session.query(TelegramActionLog).filter(TelegramActionLog.order_id == order.id)}
    assert statuses["SUPPORT_COMPARE_CONFIRM_DUPLICATE"] == "executed"
    candidate = db_session.query(SupportCompareCandidate).one()
    assert candidate.decision_status == "duplicate"


def test_review_api_returns_the_custom_configuration_of_the_order_and_of_each_candidate(client, db_session, setup):
    from app.adapters.db.models import SupportCompareJob

    order = _order(db_session, setup, "DJ-REV-CFG")
    order.custom_config = {"original": [{"key": "Name", "value": "Ann"}], "translated_vn": []}
    db_session.commit()
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    candidate = _candidate(db_session, item, 1)
    candidate.historical_job_id = _seed_pool_job(db_session, "OLD-CFG", {"original": [{"key": "Color", "value": "Red"}], "translated_vn": []})
    job = SupportCompareJob(platform_id=setup.platform.id, chat_id=CHAT_ID, status="completed", run_id=setup.run.id)
    db_session.add(job)
    db_session.commit()

    data = client.get(f"/api/support-review/jobs/{job.id}", headers=_bearer(setup.support)).json()
    [entry] = data["items"]
    assert entry["custom_config"]["original"][0]["value"] == "Ann"
    assert entry["candidates"][0]["custom_config"]["original"][0]["value"] == "Red"


def test_review_shows_live_progress_of_a_running_job(client, db_session, setup):
    from app.adapters.db.models import SupportCompareJob

    order = _order(db_session, setup, "DJ-LIVE-1")
    item = _item(db_session, setup, order, "pending_review", is_duplicate=True)
    _candidate(db_session, item, 1)
    # The run row is created when a machine claims the job, so items show up while it is still running.
    job = SupportCompareJob(
        platform_id=setup.platform.id, chat_id=CHAT_ID, status="running", requested_count=5, run_id=setup.run.id,
    )
    db_session.add(job)
    db_session.commit()

    data = client.get(f"/api/support-review/jobs/{job.id}", headers=_bearer(setup.support)).json()
    assert data["job"]["status"] == "running"
    assert (data["job"]["processed_count"], data["job"]["duplicate_count"], data["job"]["requested_count"]) == (1, 1, 5)
    assert [i["order_code"] for i in data["items"]] == ["DJ-LIVE-1"]


def test_review_image_proxy_serves_public_images_only(client, setup, monkeypatch):
    from app.api.routes import support_review_api as review

    assert review._is_public_host("127.0.0.1") is False
    assert review._is_public_host("192.168.1.10") is False
    headers = _bearer(setup.support)
    assert client.get("/api/support-review/img", params={"url": "http://127.0.0.1:5432/x.png"}, headers=headers).status_code == 400
    assert client.get("/api/support-review/img", params={"url": "file:///etc/passwd"}, headers=headers).status_code == 400
    assert client.get("/api/support-review/img", params={"url": "https://cdn.example/x.jpg"}).status_code == 401

    monkeypatch.setattr(review, "_fetch_image", lambda url: (b"RIFFwebp", "image/webp"))
    res = client.get("/api/support-review/img", params={"url": "https://cdn.example/x.jpg"}, headers=headers)
    assert res.status_code == 200 and res.content == b"RIFFwebp" and res.headers["content-type"] == "image/webp"


def test_search_rejects_empty_and_out_of_range_requests(client, setup):
    headers = _bearer(setup.support)
    png = ("a.png", b"\x89PNG", "image/png")
    assert client.post("/api/support-review/search?top_k=0", files={"file": png}, headers=headers).status_code == 400
    assert client.post("/api/support-review/search", files={"file": ("e.png", b"", "image/png")}, headers=headers).status_code == 400
    assert client.post("/api/support-review/search", files={"file": png}).status_code == 401
