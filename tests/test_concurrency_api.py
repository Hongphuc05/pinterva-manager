import asyncio
import uuid

from starlette.requests import Request
from sqlalchemy.orm.exc import StaleDataError

from app.api.main import create_app
from app.application.concurrency import OrderVersionConflictError


def test_stale_data_error_returns_safe_order_conflict_response():
    app = create_app()
    handler = app.exception_handlers[StaleDataError]
    request = Request({"type": "http", "method": "POST", "path": "/api/orders/test", "headers": []})
    response = asyncio.run(handler(request, StaleDataError("simulated stale write")))

    assert response.status_code == 409
    assert b'"code":"ORDER_VERSION_CONFLICT"' in response.body
    assert b'"current_version":null' in response.body


def test_order_version_conflict_has_machine_readable_fields():
    error = OrderVersionConflictError(
        order_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        expected_version=3,
        current_version=4,
        changed_fields=["state"],
    )

    assert error.detail() == {
        "code": "ORDER_VERSION_CONFLICT",
        "message": "Đơn đã được cập nhật bởi người khác. Hãy tải lại dữ liệu trước khi thử lại.",
        "order_id": "11111111-1111-1111-1111-111111111111",
        "expected_version": 3,
        "current_version": 4,
        "changed_fields": ["state"],
    }
