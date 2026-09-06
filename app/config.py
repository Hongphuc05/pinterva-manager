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
