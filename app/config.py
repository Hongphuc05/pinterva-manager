from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pinterval"
    secret_key: str = DEFAULT_SECRET_KEY
    cookie_secure: bool = True
    session_max_age_seconds: int = 60 * 60 * 12
    redis_url: str = "redis://localhost:6379/0"
    crawl_interval_seconds: int = 300
    # How often the read-only Printerval-status mirror (Order.printerval_status)
    # refreshes in the background — separate from crawl_interval_seconds since it's a
    # much cheaper, purely-read HTTP job (no Playwright), safe to run more often.
    status_sync_interval_seconds: int = 300
    # A manually requested tab sync talks to Printerval for only the selected orders.
    # Keep this deliberately modest: a shared session cookie can be rate-limited if a
    # browser-like burst is too large, while four concurrent reads remove most of the
    # wall-clock wait caused by one-request-per-order lookup.
    printerval_manual_sync_concurrency: int = 4
    # Comma-separated browser origins permitted to call the JSON API.  Kept explicit
    # because the Vercel SPA and API are separate production origins.
    cors_origins: str = "http://localhost:5173"
    # Optional and deliberately separate from CORS_ORIGINS: production should use an
    # exact origin, while a preview deployment can opt in to a narrowly-scoped regex.
    cors_origin_regex: str | None = None
    # These are server-side credentials only.  The SPA must never receive them.
    # They stay optional here so a normal local/test boot does not require a live
    # Printerval account; PrintervalApiClient validates them when it is used.
    printerval_api_base_url: str = "https://printerval.com"
    printerval_username: str | None = None
    printerval_password: str | None = None
    printerval_team_outsource: str | None = None
    # Google Sheets is an optional one-way reporting projection. It stays disabled
    # unless all production configuration is deliberately provided.
    google_service_account_file: str | None = None
    google_sheets_order_backup_url: str | None = None
    google_sheets_order_backup_tab: str = "Order Backup"
    order_sheet_backup_enabled: bool = False
    order_sheet_backup_hour: int = 0
    order_sheet_backup_minute: int = 10
    celery_timezone: str = "Asia/Ho_Chi_Minh"

    @field_validator("order_sheet_backup_hour")
    @classmethod
    def _validate_order_sheet_backup_hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("ORDER_SHEET_BACKUP_HOUR must be between 0 and 23")
        return value

    @field_validator("order_sheet_backup_minute")
    @classmethod
    def _validate_order_sheet_backup_minute(cls, value: int) -> int:
        if not 0 <= value <= 59:
            raise ValueError("ORDER_SHEET_BACKUP_MINUTE must be between 0 and 59")
        return value

    @field_validator("celery_timezone")
    @classmethod
    def _validate_celery_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("CELERY_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def _reject_default_secret_in_production(self) -> "Settings":
        # The default is public (it is in git), so every session cookie signed with it
        # is forgeable. cookie_secure=True marks a non-local deployment.
        if self.cookie_secure and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the built-in default while COOKIE_SECURE is true — "
                "set a real SECRET_KEY before deploying"
            )
        if self.order_sheet_backup_enabled and (
            not self.google_service_account_file or not self.google_sheets_order_backup_url
        ):
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEETS_ORDER_BACKUP_URL are required "
                "when ORDER_SHEET_BACKUP_ENABLED is true"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
