from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import object_session

from app.adapters.db.models import DeadLetter, Order, Platform, PrintervalAssignmentRequest, User
from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import PrintervalApiClient
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.application.assignment_sync import sync_assignment_to_printerval
from app.application.fix_template_confirm import mark_template_sent, stored_template_answer
from app.application.printerval_assignment_requests import execute_request
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _alert_admins(
    session, order: Order | None, *, action: str, error: str, manual: str, error_class: str = "UNKNOWN_OUTCOME"
) -> None:
    """A write to Printerval failed: record it so the Admin web shows a toast (never raises)."""
    if order is None:
        return
    from app.application.printerval_alerts import record_write_failure

    record_write_failure(session, order, action=action, error=error, manual=manual, error_class=error_class)


def _request_wording(request: PrintervalAssignmentRequest, code: str) -> tuple[str, str]:
    parts = []
    if request.designer_option:
        parts.append(f"Designer thành {request.designer_option}")
    if request.target_status:
        parts.append(f"trạng thái sang {request.target_status}")
    change = " và ".join(parts) or "cập nhật đơn"
    return f"đổi {change}", f"vào Printerval đổi {change} cho đơn {code}"


@celery_app.task(name="app.workers.assignment_sync_tasks.sync_printerval_assignment_request")
def sync_printerval_assignment_request(request_id: str) -> None:
    """Run one explicit per-order Designer/Status request for its own platform."""
    session = SessionLocal()
    try:
        request = session.get(PrintervalAssignmentRequest, uuid.UUID(request_id))
        if request is None:
            logger.error("Printerval assignment request %s not found", request_id)
            return
        order = session.get(Order, request.order_id)
        action, manual = _request_wording(request, order.external_order_id if order else "")
        platform = session.get(Platform, request.platform_id)
        if platform is None or not (platform.account_password or platform.session_cookie):
            request.lifecycle = "failed"
            request.error_class = "AUTH"
            request.error_message = "Platform credentials are unavailable"
            session.commit()
            _alert_admins(session, order, action=action, error=request.error_message, manual=manual, error_class="AUTH")
            return
        # A real browser fallback matters here specifically when a password is
        # available. Cookie-only platforms stay HTTP-only, avoiding a pointless
        # interactive login attempt with no password.
        # 2026-09-09 — a *fresh* httpx login (no persistent browser session) started
        # getting rejected with 403/AUTH after this endpoint had been hit repeatedly in
        # a short window (crawl + manual testing), even though the account/password
        # were correct — while the persistent Chrome profile (already logged in, no
        # fresh login needed per call) kept working. Without a fallback, that one
        # rejected login permanently failed the whole Designer+Status write with no
        # automatic recovery.
        clean_slug = platform.account_username.replace("@", "_").replace(".", "_").replace("+", "_")
        profile_dir = f"chrome-profile-{clean_slug}"
        fallback = None
        session_cm = None
        if platform.account_password:
            try:
                session_cm = playwright_session(profile_dir=profile_dir, headless=True)
                page = session_cm.__enter__()
                fallback = PlaywrightPrintervalAdapter(
                    page=page,
                    crawl_username=platform.account_username,
                    crawl_password=platform.account_password,
                )
            except Exception:
                logger.exception(
                    "Printerval assignment request %s: Playwright fallback failed to open, "
                    "continuing HTTP-only", request_id,
                )
                session_cm = None
        try:
            with PrintervalApiClient(
                base_url="https://printerval.com",
                username=platform.account_username,
                password=platform.account_password,
                team_outsource=platform.team_outsource,
                session_cookie=platform.session_cookie,
            ) as client:
                adapter = PrintervalApiAdapter(client, fallback_adapter=fallback, download_images=False)
                execute_request(session, adapter, request)
        finally:
            if session_cm is not None:
                session_cm.__exit__(None, None, None)
        if request.lifecycle in ("failed", "unknown_outcome"):
            _alert_admins(
                session, order, action=action, error=request.error_message or "không rõ", manual=manual,
                error_class=request.error_class or "UNKNOWN_OUTCOME",
            )
    except Exception as exc:
        logger.exception("Printerval assignment request %s crashed", request_id)
        session.rollback()
        try:
            request = session.get(PrintervalAssignmentRequest, uuid.UUID(request_id))
            order = session.get(Order, request.order_id) if request else None
            if request is not None and request.lifecycle == "pending":
                request.lifecycle = "failed"
                request.error_class = "BUG"
                request.error_message = f"{type(exc).__name__}: {exc}"[:1024]
                session.commit()
            if request is not None:
                action, manual = _request_wording(request, order.external_order_id if order else "")
                _alert_admins(session, order, action=action, error=f"{type(exc).__name__}: {exc}", manual=manual)
        except Exception:
            logger.exception("could not alert Admins about request %s", request_id)
    finally:
        session.close()


@celery_app.task(name="app.workers.assignment_sync_tasks.sync_assignment_to_printerval_task")
def sync_assignment_to_printerval_task(order_id: str, designer_id: str) -> None:
    """Triggered right after an internal assignment is created (orders_api.py), not on
    a schedule — one Playwright session per call, same shape as crawl_tasks.crawl_and_claim
    (claude.md tech debt #4: 1 session/site). A failure here is dead-lettered by
    sync_assignment_to_printerval itself (visible on Kanban's existing dead_letters-based
    alert badge) — this task only handles failures *before* that point (order/designer
    gone, platform has no credentials, browser never opened).
    """
    logger.disabled = False  # see crawl_tasks.crawl_and_claim's identical ponytail note
    session = SessionLocal()
    try:
        order = session.get(Order, uuid.UUID(order_id))
        designer = session.get(User, uuid.UUID(designer_id))
        if order is None or designer is None:
            logger.error(
                "sync_assignment_to_printerval_task: order %s or designer %s not found",
                order_id, designer_id,
            )
            return
        if not designer.printerval_designer_option:
            # Not an error — this designer just isn't registered on Printerval.
            return

        action = f"giao Designer {designer.printerval_designer_option} (Designer + Doing)"
        manual = (
            f"vào Printerval đặt Designer {designer.printerval_designer_option} và trạng thái Doing "
            f"cho đơn {order.external_order_id}"
        )
        platform = session.get(Platform, order.platform_id) if order.platform_id else None
        if platform is None or not platform.account_password:
            logger.error(
                "sync_assignment_to_printerval_task: platform credentials missing for order %s",
                order.external_order_id,
            )
            _alert_admins(session, order, action=action, error="Platform chưa có mật khẩu Printerval", manual=manual)
            return

        clean_slug = platform.account_username.replace("@", "_").replace(".", "_").replace("+", "_")
        profile_dir = f"chrome-profile-{clean_slug}"
        try:
            session_cm = playwright_session(profile_dir=profile_dir, headless=True)
            page = session_cm.__enter__()
        except Exception as exc:
            logger.exception(
                "sync_assignment_to_printerval_task: Playwright session failed to open for order %s",
                order.external_order_id,
            )
            _alert_admins(
                session, order, action=action, error=f"Không mở được trình duyệt: {type(exc).__name__}", manual=manual
            )
            return

        try:
            adapter = PlaywrightPrintervalAdapter(
                page=page,
                crawl_username=platform.account_username,
                crawl_password=platform.account_password,
            )
            try:
                result = sync_assignment_to_printerval(session, adapter, order, designer)
                logger.info(
                    "sync_assignment_to_printerval_task result for %s: %s",
                    order.external_order_id, result,
                )
                if not result.get("synced") and result.get("stage"):
                    _alert_admins(
                        session, order, action=action, error=f"Lỗi ở bước {result['stage']}", manual=manual
                    )
            except Exception as exc:
                logger.exception(
                    "sync_assignment_to_printerval_task: unexpected exception mid-run for order %s",
                    order.external_order_id,
                )
                session.rollback()
                _alert_admins(session, order, action=action, error=f"{type(exc).__name__}: {exc}", manual=manual)
        finally:
            session_cm.__exit__(None, None, None)
    finally:
        session.close()


# Printerval is sometimes very slow: a failed Review push is retried before Admin is asked to do it.
REVIEW_SYNC_RETRY_DELAYS = (60, 180, 420)
# A background write can wait longer than a web request: the cookie probe alone took 30s+ on 14/10.
REVIEW_SYNC_TIMEOUT_SECONDS = 60.0


class ReviewSyncFailed(Exception):
    """The Review/note write did not go through. ``retryable`` is False when retrying cannot help."""

    def __init__(self, message: str, *, error_class: str, retryable: bool = True, fix_template: dict | None = None):
        super().__init__(message)
        self.error_class = error_class
        self.retryable = retryable
        # Set when Printerval asks to confirm a Fix raised for "Đổi template" (see update_order_status).
        self.fix_template = fix_template


TEMPLATE_CONFIRM = "TEMPLATE_CONFIRM"


def _push_review(client: PrintervalApiClient, order: Order, note_outsource: str | None, target_status: str,
                 is_still_expected, template_confirm: dict | None = None) -> bool:
    """One attempt over the HTTP API. Returns False when the order moved on (stale job, nothing done)."""

    client.login()
    code = order.external_order_id
    numeric_id = code[2:] if code.upper().startswith("DJ") else code
    row_id = int(numeric_id)
    locale = "en"
    row = None
    try:
        # One lookup in the order's current queue only (not every status): the id is already in
        # the code, the row is needed just for its locale (us, uk, fr...). A slow or missing
        # lookup must not block the write.
        row = client.find_order(code, statuses=((order.printerval_status or "doing").lower(),))
        if row:
            row_id = int(row.get("id") or row_id)
            locale = row.get("local_code") or locale
    except Exception:
        logger.warning("locale lookup failed for %s, writing with the default locale", code, exc_info=True)

    if note_outsource and note_outsource.strip():
        if not is_still_expected():
            logger.info("Skipping stale Printerval note sync for %s", code)
            return False
        if not client.update_order_note_outsource(row_id, note_outsource.strip()):
            raise ReviewSyncFailed("Printerval không nhận ghi chú (note outsource)", error_class="UNKNOWN_OUTCOME")
        logger.info("HTTP update_order_note_outsource for %s: True", code)

    if target_status and target_status.lower() == "review":
        if not _push_design_images(client, order, row, is_still_expected):
            return False
        if (order.printerval_status or "").lower() == "fix":
            # Printerval keeps a Fix job in Fix while QC's chat messages are unread (19/10 rule);
            # reading the chat marks them read for the team. A failure here is left to Printerval's answer.
            try:
                client.fetch_chat_messages(row_id)
            except Exception:
                logger.warning("Could not read the chat of %s before leaving Fix", code, exc_info=True)

    # The Admin may already have answered Printerval's "was this Fix about the template?" while accepting
    # the Fix: send that answer along so the order leaves Fix in one go.
    if template_confirm is None and (target_status or "").lower() == "review" and (order.printerval_status or "").lower() == "fix":
        template_confirm = stored_template_answer(order, row)

    if target_status:
        if not is_still_expected():
            logger.info("Skipping stale Printerval status sync (%s) for %s", target_status, code)
            return False
        if not client.update_order_status(row_id, target_status.lower(), locale, extra=template_confirm):
            reason = getattr(client, "last_status_error", "")
            refusal = getattr(client, "last_status_refusal", None) or {}
            logger.warning("Printerval refused status %s for %s: %s", target_status, code, reason)
            if refusal.get("code") == "template_confirm":
                # A person must say whether the Fix really was about the template: never retried.
                raise ReviewSyncFailed(
                    "Printerval cần xác nhận Fix do đổi template trước khi chuyển sang "
                    f"{target_status}",
                    error_class=TEMPLATE_CONFIRM,
                    retryable=False,
                    fix_template=refusal.get("outsource_fix_template")
                    if isinstance(refusal.get("outsource_fix_template"), dict) else {},
                )
            raise ReviewSyncFailed(
                f"Printerval không nhận đổi trạng thái sang {target_status}" + (f" ({reason})" if reason else ""),
                error_class="UNKNOWN_OUTCOME",
            )
        logger.info("HTTP update_order_status (%s) for %s: True", target_status, code)
        # Save on the latest version under a row lock: a status sync may have saved the order
        # while Printerval was answering (StaleDataError otherwise).
        object_session(order).refresh(order, with_for_update=True)
        order.printerval_status = target_status.lower()
        order.printerval_status_synced_at = datetime.now(UTC)
        if template_confirm:
            mark_template_sent(order)
    return True


def _push_design_images(client: PrintervalApiClient, order: Order, row: dict | None, is_still_expected) -> bool:
    """Put the submitted mockups not yet on Printerval into the job's Design column (required for
    Review since 19/10). Each image is recorded as soon as Printerval has it, so a retry never uploads
    it twice. Returns False when the order moved on."""
    from app.application.result_images import image_path, images_to_push

    session = object_session(order)
    images = images_to_push(session, order)
    if not images:
        return True
    if not is_still_expected():
        logger.info("Skipping stale mockup upload for %s", order.external_order_id)
        return False
    if row is None:
        row = client.find_order(order.external_order_id)
    if not row:
        raise ReviewSyncFailed(
            "Không đọc được đơn trên Printerval để tải ảnh mockup", error_class="TRANSIENT_NETWORK"
        )
    has_designs = bool(row.get("designs"))
    for image in images:
        path = image_path(image)
        if not path.is_file():
            raise ReviewSyncFailed(
                f"Mất file ảnh mockup {image.original_filename} trên máy chủ Tacahu, designer cần gắn lại",
                error_class="BUG", retryable=False,
            )
        url = client.upload_design_file(image.original_filename, path.read_bytes(), image.content_type)
        stored = client.store_design_images(
            row, [url],
            resolution=f"{image.width}x{image.height}" if image.width and image.height else None,
            is_primary=not has_designs,
        )
        has_designs = True
        image.printerval_image_url = url[:1024]
        image.printerval_design_id = int(stored[-1]["id"]) if stored and str(stored[-1].get("id", "")).isdigit() else None
        image.pushed_at = datetime.now(UTC)
        session.commit()
        logger.info("Mockup %s uploaded to the Design column of %s", image.id, order.external_order_id)
    return True


@celery_app.task(
    bind=True,
    name="app.workers.assignment_sync_tasks.sync_order_review_to_printerval_task",
    max_retries=len(REVIEW_SYNC_RETRY_DELAYS),
)
def sync_order_review_to_printerval_task(
    self,
    order_id: str,
    note_outsource: str | None = None,
    target_status: str = "Review",
    *,
    expected_state: str | None = None,
    expected_fix_approved: bool | None = None,
    template_confirm: dict | None = None,
    alert_id: str | None = None,
    last_error: str | None = None,
) -> None:
    """Sync a note and/or status to Printerval only when its workflow is still current.

    ``template_confirm`` is the Admin's answer when Printerval asked to confirm a Fix raised for
    "Đổi template"; ``alert_id`` is that request's DeadLetter, resolved once the push goes through.
    ``last_error`` is carried across retries so a job that gives up because the order moved on
    still says what had failed.

    A Designer's Review submission is asynchronous.  Without the expectation
    guard, a delayed Review job could run after an Admin has accepted a newer
    Fix request and incorrectly overwrite Printerval's Fix status.  Callers
    that represent a state transition must therefore pass the state they
    observed when enqueueing the job.

    A transient failure (slow Printerval, network) is retried after 1, 3 and 7 minutes; when it
    still fails, or cannot be retried, a DeadLetter is written and the Admins are told on Telegram
    to change the status by hand. There is no browser fallback: it cannot run in production.
    """
    logger.disabled = False
    session = SessionLocal()
    try:
        order = session.get(Order, uuid.UUID(order_id))
        if order is None:
            logger.error("sync_order_review_to_printerval_task: order %s not found", order_id)
            return

        def is_still_expected() -> bool:
            """Reload before each external write so delayed jobs cannot win a newer flow."""
            session.refresh(order)
            if expected_state and (order.state or "").upper() != expected_state.upper():
                return False
            if (
                expected_fix_approved is not None
                and bool(order.fix_approved_by_admin) != expected_fix_approved
            ):
                return False
            return True

        action = f"đổi trạng thái sang {target_status}" if target_status else "ghi note outsource"

        def moved_on() -> None:
            """The order changed meanwhile. Fine for a first attempt; after a failed one it is not."""
            logger.info(
                "Skipping stale Printerval %s sync for %s (expected_state=%s, expected_fix_approved=%s)",
                target_status, order.external_order_id, expected_state, expected_fix_approved,
            )
            if self.request.retries:
                _review_sync_gave_up(
                    session, order, action, target_status,
                    ReviewSyncFailed(
                        f"{last_error or 'Lần đẩy trước thất bại'}; đơn đã đổi trạng thái trên Tacahu nên không thử lại",
                        error_class="UNKNOWN_OUTCOME", retryable=False,
                    ),
                )

        if not is_still_expected():
            moved_on()
            return

        platform = session.get(Platform, order.platform_id) if order.platform_id else None
        if platform is None or not (platform.account_password or platform.session_cookie):
            _review_sync_gave_up(
                session, order, action, target_status,
                ReviewSyncFailed("Platform chưa có cookie hoặc mật khẩu Printerval", error_class="AUTH",
                                 retryable=False),
            )
            return

        try:
            with PrintervalApiClient(
                base_url="https://printerval.com",
                username=platform.account_username,
                password=platform.account_password,
                team_outsource=platform.team_outsource,
                session_cookie=platform.session_cookie,
                timeout=REVIEW_SYNC_TIMEOUT_SECONDS,
            ) as client:
                if _push_review(client, order, note_outsource, target_status, is_still_expected,
                                template_confirm=template_confirm):
                    if alert_id:
                        alert = session.get(DeadLetter, uuid.UUID(alert_id))
                        if alert is not None and alert.resolved_at is None:
                            alert.resolved_at = datetime.now(UTC)
                    session.commit()
                    logger.info(
                        "sync_order_review_to_printerval_task succeeded via HTTP API for %s",
                        order.external_order_id,
                    )
                else:
                    moved_on()
                return
        except Exception as exc:
            session.rollback()
            failure = _as_review_failure(exc)
            attempt = self.request.retries
            if failure.retryable and attempt < len(REVIEW_SYNC_RETRY_DELAYS):
                logger.warning(
                    "Review sync for %s failed (%s: %s), retry %s/%s",
                    order.external_order_id, failure.error_class, failure,
                    attempt + 1, len(REVIEW_SYNC_RETRY_DELAYS),
                )
                raise self.retry(
                    countdown=REVIEW_SYNC_RETRY_DELAYS[attempt], exc=exc,
                    kwargs={**(self.request.kwargs or {}), "last_error": str(failure)},
                ) from exc
            _review_sync_gave_up(session, order, action, target_status, failure)
    finally:
        session.close()


def _as_review_failure(exc: Exception) -> ReviewSyncFailed:
    from app.adapters.printerval.api_client import PrintervalApiError

    if isinstance(exc, ReviewSyncFailed):
        return exc
    if isinstance(exc, PrintervalApiError):
        error_class = getattr(exc.error_class, "value", str(exc.error_class))
        # A rejected session cannot fix itself by waiting; everything else may.
        return ReviewSyncFailed(str(exc), error_class=error_class, retryable=error_class != "AUTH")
    return ReviewSyncFailed(f"{type(exc).__name__}: {exc}", error_class="TRANSIENT_NETWORK")


def _review_sync_gave_up(session, order: Order, action: str, target_status: str | None,
                         failure: ReviewSyncFailed) -> None:
    """Record the failure so the Admin web asks for the change to be done on Printerval by hand."""
    if failure.error_class == TEMPLATE_CONFIRM:
        logger.warning("Review sync for %s waits for the Admin's template confirmation", order.external_order_id)
        from app.application.printerval_alerts import record_write_failure

        record_write_failure(
            session, order, action=action, error=str(failure), error_class=TEMPLATE_CONFIRM,
            manual=f"mở đơn {order.external_order_id} trên Tacahu và xác nhận Fix có phải do đổi template không",
            extra={"kind": "template_confirm", "target_status": target_status, "fix_template": failure.fix_template or {}},
        )
        return
    manual = (
        f"vào Printerval chuyển đơn {order.external_order_id} sang {target_status}"
        if target_status
        else f"vào Printerval ghi lại note outsource cho đơn {order.external_order_id}"
    )
    logger.error("Review sync for %s gave up: %s (%s)", order.external_order_id, failure, failure.error_class)
    _alert_admins(session, order, action=action, error=str(failure), manual=manual, error_class=failure.error_class)


@celery_app.task(
    bind=True,
    name="app.workers.assignment_sync_tasks.send_fix_dispute_task",
    max_retries=len(REVIEW_SYNC_RETRY_DELAYS),
)
def send_fix_dispute_task(self, order_id: str) -> None:
    """Send the Admin's "Báo fix không đúng" to Printerval, then confirm the job went to Review.

    Never sent twice: if Printerval already holds a pending dispute for the job (an earlier attempt
    landed but its answer was lost), that is taken as sent. Transient failures are retried after 1, 3
    and 7 minutes; a refusal or the last failure marks the dispute failed and toasts the Admins, who
    can send it again from the order."""
    from app.adapters.printerval.api_client import PrintervalApiError
    from app.application import fix_dispute
    from app.application.printerval_alerts import record_write_failure

    session = SessionLocal()
    try:
        order = session.get(Order, uuid.UUID(order_id))
        record = fix_dispute.current(order) if order is not None else None
        if record is None or record.get("push") != "queued":
            return
        code = order.external_order_id

        def fail(error: str, error_class: str = "PERMANENT_EXTERNAL") -> None:
            fix_dispute.mark_failed(session, order, error)
            session.commit()
            record_write_failure(
                session, order, action="gửi khiếu nại Fix (Báo fix không đúng)", error=error,
                error_class=error_class,
                manual=f"mở đơn {code} trên Tacahu và bấm Gửi lại, hoặc báo fix không đúng trực tiếp trên Printerval",
            )

        platform = session.get(Platform, order.platform_id) if order.platform_id else None
        if platform is None or not (platform.account_password or platform.session_cookie):
            fail("Platform chưa có cookie hoặc mật khẩu Printerval", "AUTH")
            return
        try:
            with PrintervalApiClient(
                base_url="https://printerval.com",
                username=platform.account_username,
                password=platform.account_password,
                team_outsource=platform.team_outsource,
                session_cookie=platform.session_cookie,
                timeout=REVIEW_SYNC_TIMEOUT_SECONDS,
            ) as client:
                row = client.find_order(code, statuses=("fix", "review"))
                existing = row.get("outsource_fix_dispute") if row else None
                already_sent = isinstance(existing, dict) and existing.get("status") == fix_dispute.PENDING
                if not already_sent:
                    if row is None or str(row.get("status") or "").lower() != "fix":
                        fail("Đơn không còn ở Fix trên Printerval")
                        return
                    if row.get("outsource_fix_dispute_can") is False:
                        fail("Printerval không cho khiếu nại lượt Fix này")
                        return
                    client.submit_fix_dispute(int(code.upper().removeprefix("DJ")), record["note"], record["images"])
                    row = client.find_order(code, statuses=("review", "fix")) or row
                fix_dispute.mark_sent(order)
                fix_dispute.observe(
                    session, order,
                    status=row.get("status"),
                    dispute=row.get("outsource_fix_dispute") if isinstance(row.get("outsource_fix_dispute"), dict) else None,
                    can=row.get("outsource_fix_dispute_can") if isinstance(row.get("outsource_fix_dispute_can"), bool) else None,
                )
                order.printerval_status = str(row.get("status") or order.printerval_status or "").lower() or None
                order.printerval_status_synced_at = datetime.now(UTC)
                session.commit()
                logger.info("Fix dispute sent to Printerval for %s", code)
        except Exception as exc:
            session.rollback()
            failure = _as_review_failure(exc)
            # A refusal (job not disputable, bad input) will not change by waiting; a timeout may have
            # landed, which the next attempt checks before sending again.
            retryable = exc.retryable if isinstance(exc, PrintervalApiError) else True
            if retryable and self.request.retries < len(REVIEW_SYNC_RETRY_DELAYS):
                raise self.retry(countdown=REVIEW_SYNC_RETRY_DELAYS[self.request.retries], exc=exc) from exc
            session.refresh(order)
            fail(str(failure), failure.error_class)
    finally:
        session.close()
