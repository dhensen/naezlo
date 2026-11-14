"""Application settings, read from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The product name is a working name; keep it here and nowhere else in the backend.
    app_name: str = "todolist"
    environment: Literal["development", "test", "production"] = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
