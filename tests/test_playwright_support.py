from pathlib import Path

from app.adapters.playwright_support import capture_evidence, with_retry


class _FakeResult:
    def __init__(self, success, retryable):
        self.success = success
        self.retryable = retryable


def test_with_retry_returns_immediately_on_success():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=True, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is True
    assert calls["count"] == 1


def test_with_retry_returns_immediately_on_non_retryable_failure():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=False, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is False
    assert calls["count"] == 1


def test_with_retry_retries_up_to_max_attempts_on_retryable_failure():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=False, retryable=True)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is False
    assert calls["count"] == 3


def test_with_retry_stops_once_a_later_attempt_succeeds():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        if calls["count"] < 2:
            return _FakeResult(success=False, retryable=True)
        return _FakeResult(success=True, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is True
    assert calls["count"] == 2


class _FakePage:
    def __init__(self, url="https://example.test/order/1"):
        self.url = url

    def screenshot(self, path):
        Path(path).write_bytes(b"fake-png-bytes")

    def content(self):
        return "<html>fake</html>"


def test_capture_evidence_writes_screenshot_and_html(tmp_path, monkeypatch):
    import app.adapters.playwright_support as ps

    monkeypatch.setattr(ps, "EVIDENCE_DIR", tmp_path / "evidence")

    page = _FakePage()
    evidence = capture_evidence(page, "test_label")

    assert Path(evidence["screenshot_path"]).exists()
    assert Path(evidence["html_path"]).read_text() == "<html>fake</html>"
    assert evidence["url"] == page.url
    assert "captured_at" in evidence
