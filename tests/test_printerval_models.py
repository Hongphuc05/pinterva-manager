from app.adapters.errors import ErrorClass
from app.adapters.printerval.models import DiscoverResult, WriteResult


def test_error_class_has_all_eight_values():
    assert {e.value for e in ErrorClass} == {
        "VALIDATION",
        "AUTH",
        "RATE_LIMIT",
        "TRANSIENT_NETWORK",
        "EXTERNAL_CHANGED",
        "UNKNOWN_OUTCOME",
        "PERMANENT_EXTERNAL",
        "BUG",
    }


def test_discover_result_defaults():
    result = DiscoverResult(success=True)
    assert result.orders == []
    assert result.cursor is None
    assert result.error_class is None


def test_write_result_requires_external_order_id():
    result = WriteResult(success=True, external_order_id="DJ0000001")
    assert result.observed_state == {}


def test_write_result_accepts_error_class_from_plain_string():
    result = WriteResult(
        success=False, external_order_id="DJ0000001", error_class="VALIDATION"
    )
    assert result.error_class == ErrorClass.VALIDATION
