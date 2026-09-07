import pytest

from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.adapters.printerval.smoke_harness import (
    restore_order,
    run_write_method_smoke_test,
    snapshot_order,
)


def _seeded_adapter():
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ0000001",
        product_name="Test product",
        designer="Nguyễn Thị Thuý Hường - 2D Prin",
        status="Doing",
    )
    return adapter


def test_snapshot_order_captures_current_state():
    adapter = _seeded_adapter()
    snapshot = snapshot_order(adapter, "DJ0000001")
    assert snapshot.designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert snapshot.status == "Doing"


def test_restore_order_reverts_to_snapshot():
    adapter = _seeded_adapter()
    snapshot = snapshot_order(adapter, "DJ0000001")
    adapter.set_designer("DJ0000001", "Chưa chia cho ai")
    adapter.set_status("DJ0000001", "Waiting")

    restore_order(adapter, snapshot)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.designer == snapshot.designer
    assert detail.status == snapshot.status


def test_run_write_method_smoke_test_restores_after_action():
    adapter = _seeded_adapter()

    def action(adapter, order_id):
        return adapter.set_status(order_id, "Waiting")

    run_write_method_smoke_test(adapter, "DJ0000001", action)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"  # restored, not left as "Waiting"


def test_run_write_method_smoke_test_still_restores_if_action_raises():
    adapter = _seeded_adapter()

    def action(adapter, order_id):
        adapter.set_status(order_id, "Waiting")
        raise RuntimeError("simulated failure mid-action")

    with pytest.raises(RuntimeError, match="simulated failure"):
        run_write_method_smoke_test(adapter, "DJ0000001", action)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"  # still restored despite the raise


def test_restore_order_reverts_note_outsource():
    adapter = _seeded_adapter()
    adapter.attach_result_link("DJ0000001", "https://drive.google.com/original")
    snapshot = snapshot_order(adapter, "DJ0000001")
    adapter.attach_result_link("DJ0000001", "https://drive.google.com/changed")

    restore_order(adapter, snapshot)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.note_outsource == snapshot.note_outsource == "https://drive.google.com/original"


def test_snapshot_order_raises_for_unknown_order():
    adapter = _seeded_adapter()
    with pytest.raises(RuntimeError, match="Cannot snapshot"):
        snapshot_order(adapter, "DJ_NOPE")
