from __future__ import annotations

from app.adapters.playwright_support import close_playwright_session, open_playwright_session
from app.adapters.printerval.playwright_adapter import ADMIN_URL

# Module-level state for the interactive "log in to Printerval" flow: one admin, one
# browser window, opened by one request and closed by a later one — a plain global is
# enough for this single-operator, rare, admin-only action. None means no interactive
# login window is currently open. Extracted from web.py so both the old Jinja2 routes
# (until Task 6 deletes them) and the new JSON API can share the same live session
# instead of each holding a separate, inconsistent one.
_login_session: dict | None = None


def is_session_open() -> bool:
    global _login_session
    if _login_session is not None:
        try:
            _ = _login_session["context"].pages  # cheap liveness check
        except Exception:
            _login_session = None
    return _login_session is not None


def start_session() -> None:
    global _login_session
    if not is_session_open():
        playwright_cm, context, page = open_playwright_session()
        page.goto(ADMIN_URL)
        _login_session = {"playwright_cm": playwright_cm, "context": context}


def close_session() -> None:
    global _login_session
    if _login_session is not None:
        close_playwright_session(_login_session["playwright_cm"], _login_session["context"])
        _login_session = None
