from __future__ import annotations

import random
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from playwright.sync_api import Page, sync_playwright

EVIDENCE_DIR = Path("playwright-evidence")

T = TypeVar("T")


@contextmanager
def playwright_session(profile_dir: str = "chrome-profile", headless: bool = False):
    """Launch a persistent Chrome profile, yield the Page to use.

    The profile directory must already be logged into Printerval (done once,
    interactively, by a human — Cloudflare + the site's login flow are not
    automated here). Reusing the persistent profile avoids re-login on every
    run, matching how Phase 0's exploration worked.
    """
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            context.close()


def with_retry(fn: Callable[[], T], max_attempts: int = 3, base_delay: float = 0.5) -> T:
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
    """Screenshot + HTML dump + timestamp; returns paths for an `evidence` field."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    base = f"{label}_{timestamp}"
    screenshot_path = EVIDENCE_DIR / f"{base}.png"
    html_path = EVIDENCE_DIR / f"{base}.html"
    page.screenshot(path=str(screenshot_path))
    html_path.write_text(page.content())
    return {
        "screenshot_path": str(screenshot_path),
        "html_path": str(html_path),
        "url": page.url,
        "captured_at": timestamp,
    }
