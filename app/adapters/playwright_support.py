from __future__ import annotations

import random
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

EVIDENCE_DIR = Path("playwright-evidence")


def cleanup_profile_locks(profile_dir: str = "chrome-profile") -> None:
    path = Path(profile_dir)
    if path.exists():
        for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_file = path / lock_name
            if lock_file.exists() or lock_file.is_symlink():
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass


def open_playwright_session(profile_dir: str = "chrome-profile", headless: bool = False):
    """Low-level open: launch the persistent Chrome profile and return
    `(playwright_cm, context, page)` WITHOUT closing anything — the caller owns
    cleanup via `close_playwright_session(playwright_cm, context)`.

    Prefer the `playwright_session()` context manager below for the common case
    (auto-closes on exit). This lower-level function exists only for flows that must
    keep the browser open across multiple separate requests — e.g. the web
    dashboard's interactive "log in to Printerval" flow, where a human needs an
    unpredictable amount of time to type credentials between one HTTP request opening
    the browser and a second, later one closing it; a single `with` block can't span
    two separate request/response cycles.
    """
    cleanup_profile_locks(profile_dir)
    playwright_cm = sync_playwright()
    p = playwright_cm.__enter__()
    context = p.chromium.launch_persistent_context(
        profile_dir,
        channel="chrome",
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else context.new_page()
    return playwright_cm, context, page


def close_playwright_session(playwright_cm, context) -> None:
    """Counterpart to `open_playwright_session` — closes the browser context, then
    tears down the underlying Playwright driver process. Safe to call even if the
    context was already closed manually (e.g. the user closed the window themselves).
    """
    try:
        context.close()
    finally:
        playwright_cm.__exit__(None, None, None)


@contextmanager
def playwright_session(profile_dir: str = "chrome-profile", headless: bool = False):
    """Launch a persistent Chrome profile, yield the Page to use.

    The profile directory must already be logged into Printerval (done once,
    interactively, by a human — Cloudflare + the site's login flow are not
    automated here; the web dashboard's "Đăng nhập Printerval" page drives this same
    profile through `open_playwright_session`/`close_playwright_session` for that
    one-time interactive step). Reusing the persistent profile avoids re-login on
    every run, matching how Phase 0's exploration worked.
    """
    playwright_cm, context, page = open_playwright_session(profile_dir, headless)
    try:
        yield page
    finally:
        close_playwright_session(playwright_cm, context)


def with_retry[T](fn: Callable[[], T], max_attempts: int = 3, base_delay: float = 0.5) -> T:
    """Call fn() up to max_attempts times while its result is retryable.

    fn() must return an object with boolean `.success` and `.retryable`
    attributes (every AdapterResult subclass qualifies). A successful result,
    or a failure with retryable=False, returns immediately on the first
    attempt.
    """
    last_result = None
    for attempt in range(1, max_attempts + 1):
        result = fn()
        if result.success or not result.retryable:
            return result
        last_result = result
        if attempt < max_attempts:
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            time.sleep(delay)
    return last_result


def capture_evidence(page: Page, label: str) -> dict:
    """Screenshot + HTML dump + timestamp; returns paths for an `evidence` field.

    Never raises: if the page is already closed or mid-navigation (a common reason the
    *original* failure happened), screenshot/content capture can itself fail — this
    must not replace the caller's typed failure result with an unhandled exception, so
    any capture failure here is recorded in the returned dict instead of propagating.
    """
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    base = f"{label}_{timestamp}"
    screenshot_path = EVIDENCE_DIR / f"{base}.png"
    html_path = EVIDENCE_DIR / f"{base}.html"
    evidence: dict = {"captured_at": timestamp}
    try:
        page.screenshot(path=str(screenshot_path))
        evidence["screenshot_path"] = str(screenshot_path)
    except Exception as exc:
        evidence["screenshot_error"] = str(exc)
    try:
        html_path.write_text(page.content())
        evidence["html_path"] = str(html_path)
    except Exception as exc:
        evidence["html_error"] = str(exc)
    try:
        evidence["url"] = page.url
    except Exception as exc:
        evidence["url_error"] = str(exc)
    return evidence
