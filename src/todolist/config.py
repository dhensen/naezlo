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

    # The defaults match docker-compose.yml.
    database_url: str = "postgresql+asyncpg://todolist:todolist@localhost:5435/todolist"
    # Only the test suite uses this one; it wipes and re-migrates that database.
    test_database_url: str = "postgresql+asyncpg://todolist:todolist@localhost:5435/todolist_test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
