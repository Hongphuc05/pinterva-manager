from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """A required setting is missing."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str | None = None

    def validate_database_url(self) -> str:
        if not self.database_url or not self.database_url.strip():
            raise ConfigurationError("DATABASE_URL is required for database migration")
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
