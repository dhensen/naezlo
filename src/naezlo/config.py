"""Application settings, read from environment variables and an optional `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from fastapi import Depends, Request
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Signs session cookies when SESSION_SECRET is not set. Fine on a laptop, refused in production.
DEV_SESSION_SECRET = "dev-only-session-secret-not-for-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The product name is a working name; keep it here and nowhere else in the backend.
    app_name: str = "Naezlo"
    environment: Literal["development", "test", "production"] = "development"

    # The defaults match docker-compose.yml.
    database_url: str = "postgresql+asyncpg://todolist:todolist@localhost:5435/todolist"
    # Only the test suite uses this one; it wipes and re-migrates that database.
    test_database_url: str = "postgresql+asyncpg://todolist:todolist@localhost:5435/todolist_test"
    # Only the browser tests use this one (`python -m naezlo.e2e` wipes and re-migrates it).
    e2e_database_url: str = "postgresql+asyncpg://todolist:todolist@localhost:5435/todolist_e2e"

    # Signs the session cookie. Generate one with: openssl rand -hex 32
    session_secret: str = DEV_SESSION_SECRET
    # Enables POST /api/auth/dev-login, which signs in as any email without a password.
    dev_login: bool = False

    # The URL people reach the app on in their browser (no path). Absolute URLs that leave the
    # app, such as the Google redirect URI, are built from it and never from the Host header.
    public_base_url: str = "http://localhost:8000"

    # The built frontend (`npm --prefix frontend run build`). When it has an index.html at startup,
    # the app serves it on every path the backend does not own; otherwise only the backend runs.
    # Relative to the working directory.
    frontend_dist: Path | None = Path("frontend/dist")

    # Google OAuth client ("Web application" type). Google login is on when both are set.
    google_client_id: str | None = None
    google_client_secret: str | None = None

    @property
    def session_cookie_secure(self) -> bool:
        """The session cookie is HTTPS-only everywhere except local development and tests."""
        return self.environment == "production"

    @property
    def google_login_enabled(self) -> bool:
        """Google login needs both halves of the OAuth client."""
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def google_redirect_uri(self) -> str:
        """The callback URL registered with Google as an authorized redirect URI."""
        return f"{self.public_base_url.rstrip('/')}/api/auth/google/callback"

    @property
    def oauth_issuer(self) -> str:
        """The issuer identifier of the built-in OAuth authorization server (no trailing slash).

        Clients compare it as a string with what they discovered, so build every OAuth URL from it.
        """
        return self.public_base_url.rstrip("/")

    @property
    def mcp_resource_url(self) -> str:
        """The MCP endpoint: the OAuth resource (RFC 8707 / RFC 9728) that tokens are issued for."""
        return f"{self.oauth_issuer}/mcp"

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> Self:
        if self.environment == "production":
            if self.session_secret == DEV_SESSION_SECRET:
                raise ValueError("SESSION_SECRET must be set when ENVIRONMENT=production")
            if self.dev_login:
                raise ValueError("DEV_LOGIN must not be enabled when ENVIRONMENT=production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _app_settings(request: Request) -> Settings:
    return request.app.state.settings


# Use this in route signatures: `settings: SettingsDep` (the `Settings` the app was built with).
SettingsDep = Annotated[Settings, Depends(_app_settings)]
