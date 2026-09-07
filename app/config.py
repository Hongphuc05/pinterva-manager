from functools import lru_cache

from pydantic import model_validator
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
    # These are server-side credentials only.  The SPA must never receive them.
    # They stay optional here so a normal local/test boot does not require a live
    # Printerval account; PrintervalApiClient validates them when it is used.
    printerval_api_base_url: str = "https://printerval.com"
    printerval_username: str | None = None
    printerval_password: str | None = None
    printerval_team_outsource: str | None = None

    @model_validator(mode="after")
    def _reject_default_secret_in_production(self) -> "Settings":
        # The default is public (it is in git), so every session cookie signed with it
        # is forgeable. cookie_secure=True marks a non-local deployment.
        if self.cookie_secure and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the built-in default while COOKIE_SECURE is true — "
                "set a real SECRET_KEY before deploying"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
