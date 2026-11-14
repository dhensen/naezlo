"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.middleware.sessions import SessionMiddleware

from todolist.api import api_router
from todolist.api.oauth import root_router as oauth_root_router
from todolist.config import Settings, get_settings
from todolist.db import create_engine, create_session_factory
from todolist.errors import install_error_handlers
from todolist.google import GoogleClient

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Creating the engine does not connect; the first query does.
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    # None when Google login is not configured; the Google routes then answer 404.
    app.state.google = (
        GoogleClient(settings.google_client_id, settings.google_client_secret)
        if settings.google_client_id and settings.google_client_secret
        else None
    )
    # Signed cookie session. Starlette always sets HttpOnly on it.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.session_cookie_secure,
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)
    app.include_router(oauth_root_router)
    return app
