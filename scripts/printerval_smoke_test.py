#!/usr/bin/env python3
"""
Manual, supervised smoke test for the real Playwright Printerval adapter.

NOT part of the pytest/CI suite. Run by hand when verifying a real write
method against production, per the safety rule in
docs/superpowers/specs/2026-09-07-phase2-adapter-design.md §1: every write
must snapshot -> act -> verify -> restore -> verify-restore.

Usage:
    python scripts/printerval_smoke_test.py DJ0000001 --method set_status --value Doing
"""
from __future__ import annotations

import argparse

from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.adapters.printerval.smoke_harness import run_write_method_smoke_test


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id", help="Mã đơn DJ####### để test")
    parser.add_argument(
        "--method",
        choices=["set_designer", "set_status", "attach_result_link"],
        required=True,
    )
    parser.add_argument(
        "--value", required=True, help="Giá trị mới để test (designer/status/drive_url)"
    )
    args = parser.parse_args()

    with playwright_session() as page:
        adapter = PlaywrightPrintervalAdapter(page)

        def action(adapter, order_id):
            method = getattr(adapter, args.method)
            return method(order_id, args.value)

        run_write_method_smoke_test(adapter, args.order_id, action)

    print(f"Smoke test PASSED for {args.method} on {args.order_id} — state restored.")


if __name__ == "__main__":
    main()
