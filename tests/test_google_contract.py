from unittest.mock import patch

from app.adapters.google.drive_interface import DriveAdapter
from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter
from app.adapters.google.sheets_interface import SheetsAdapter


def test_fake_sheets_adapter_conforms_to_protocol():
    adapter = FakeSheetsAdapter()
    assert isinstance(adapter, SheetsAdapter)


def test_fake_drive_adapter_conforms_to_protocol():
    adapter = FakeDriveAdapter(known_file_ids=set())
    assert isinstance(adapter, DriveAdapter)


def test_real_sheets_adapter_conforms_to_protocol():
    with (
        patch("app.adapters.google.sheets_adapter.service_account.Credentials.from_service_account_file"),
        patch("app.adapters.google.sheets_adapter.build"),
    ):
        from app.adapters.google.sheets_adapter import GoogleSheetsAdapter

        adapter = GoogleSheetsAdapter(credentials_path="unused")
        assert isinstance(adapter, SheetsAdapter)


def test_real_drive_adapter_conforms_to_protocol():
    with (
        patch("app.adapters.google.drive_adapter.service_account.Credentials.from_service_account_file"),
        patch("app.adapters.google.drive_adapter.build"),
    ):
        from app.adapters.google.drive_adapter import GoogleDriveAdapter

        adapter = GoogleDriveAdapter(credentials_path="unused")
        assert isinstance(adapter, DriveAdapter)
