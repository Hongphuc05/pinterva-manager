"""Unit tests for PlaywrightPrintervalAdapter's error paths, using minimal
fakes for the Playwright surface (_search_and_get_row and capture_evidence
are monkeypatched at the module level — the rest of Playwright's API isn't
exercised here, that's what the smoke harness against a real page is for).
"""

import app.adapters.printerval.playwright_adapter as pa


class _FakeLocator:
    def __init__(self, count=1, href=None):
        self._count = count
        self._href = href
        self.first = self

    def count(self):
        return self._count

    def get_attribute(self, name):
        return self._href


class _FakeRow:
    def locator(self, selector):
        if selector == "a.djcfg-src-link":
            return _FakeLocator(count=1, href="https://cdn.example.test/file.png")
        raise AssertionError(f"unexpected locator {selector!r}")


class _FakeRequestResponse:
    def __init__(self, ok, status=403, body=b""):
        self.ok = ok
        self.status = status
        self._body = body

    def body(self):
        return self._body


class _FakeRequestContext:
    def __init__(self, response):
        self._response = response

    def get(self, url):
        return self._response


class _FakePage:
    def __init__(self, response):
        self.url = "https://example.test"
        self.request = _FakeRequestContext(response)


def test_download_asset_returns_failure_and_writes_nothing_on_non_ok_response(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pa, "capture_evidence", lambda page, label: {})
    monkeypatch.setattr(pa, "_search_and_get_row", lambda page, order_id: _FakeRow())
    monkeypatch.chdir(tmp_path)

    response = _FakeRequestResponse(ok=False, status=403, body=b"cdn error body")
    page = _FakePage(response)
    adapter = pa.PlaywrightPrintervalAdapter(page=page)

    result = adapter.download_asset("DJ0000001")

    assert result.success is False
    assert result.error_class is not None
    assert result.local_path is None
    assert not (tmp_path / "order_assets").exists()


class _FakeSelect:
    def __init__(self, text):
        self._text = text

    def evaluate(self, script):
        return self._text


class _FakeSelects:
    def __init__(self, texts):
        self._texts = texts

    def count(self):
        return len(self._texts)

    def nth(self, index):
        return _FakeSelect(self._texts[index])


class _FakeDesignerRow:
    def __init__(self, designer_text):
        self._designer_text = designer_text

    def locator(self, selector):
        if selector == "select":
            return _FakeSelects([self._designer_text])
        raise AssertionError(f"unexpected locator {selector!r}")


def test_set_designer_verify_failure_after_successful_save_is_unknown_outcome(monkeypatch):
    monkeypatch.setattr(pa, "capture_evidence", lambda page, label: {})

    calls = {"n": 0}

    def fake_search(page, order_id):
        calls["n"] += 1
        if calls["n"] == 1:
            # Already the target value, so set_designer skips straight to the
            # fresh-state check without needing a fake save response.
            return _FakeDesignerRow(designer_text="Target Designer")
        # The fresh-state re-read (post-save) is what fails here.
        raise pa._OrderNotFoundError("order vanished from search results")

    monkeypatch.setattr(pa, "_search_and_get_row", fake_search)

    adapter = pa.PlaywrightPrintervalAdapter(page=object())

    result = adapter.set_designer("DJ0000001", "Target Designer")

    assert result.success is False
    assert result.error_class == "UNKNOWN_OUTCOME"
    assert result.retryable is False
    assert calls["n"] == 2
