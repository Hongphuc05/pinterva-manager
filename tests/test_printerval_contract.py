from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.adapters.printerval.interface import PrintervalAdapter
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter


def test_fake_adapter_conforms_to_protocol():
    adapter = FakePrintervalAdapter()
    assert isinstance(adapter, PrintervalAdapter)


def test_playwright_adapter_conforms_to_protocol():
    # A dummy page object is enough — __init__ only stores it, no I/O happens here.
    adapter = PlaywrightPrintervalAdapter(page=object())
    assert isinstance(adapter, PrintervalAdapter)
