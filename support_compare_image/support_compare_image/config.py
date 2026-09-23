from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CrawlConfigurationError(ValueError):
    """The crawler was started without a safe/complete configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str | None = None
    printerval_api_base_url: str = "https://printerval.com"
    printerval_username: str | None = None
    printerval_password: str | None = None
    printerval_session_cookie: str | None = None
    printerval_team_outsource: str = Field(min_length=1)
    printerval_page_size: int = 100
    printerval_request_delay_seconds: float = 0.25
    printerval_timeout_seconds: float = 30.0
    printerval_max_retries: int = 5

    @field_validator("printerval_page_size")
    @classmethod
    def validate_page_size(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("PRINTERVAL_PAGE_SIZE must be between 1 and 100")
        return value

    @field_validator("printerval_request_delay_seconds", "printerval_timeout_seconds")
    @classmethod
    def validate_positive_float(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Printerval timing settings cannot be negative")
        return value

    @field_validator("printerval_max_retries")
    @classmethod
    def validate_retries(cls, value: int) -> int:
        if value < 0:
            raise ValueError("PRINTERVAL_MAX_RETRIES cannot be negative")
        return value

    def validate_printerval_auth(self) -> None:
        if self.printerval_session_cookie and self.printerval_session_cookie.strip():
            return
        if self.printerval_username and self.printerval_password:
            return
        raise CrawlConfigurationError(
            "Set PRINTERVAL_SESSION_COOKIE or both PRINTERVAL_USERNAME and "
            "PRINTERVAL_PASSWORD."
        )

    def validate_database_url(self) -> str:
        if not self.database_url or not self.database_url.strip():
            raise CrawlConfigurationError("DATABASE_URL is required for database migration/crawl")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
