"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route

from todolist.api import api_router
from todolist.api.oauth import root_router as oauth_root_router
from todolist.config import Settings, get_settings
from todolist.db import create_engine, create_session_factory, transaction
from todolist.errors import install_error_handlers
from todolist.google import GoogleClient
from todolist.mcp_server import create_mcp_server, mcp_asgi_app
from todolist.mcp_server.server import MCP_PATH

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Creating the engine does not connect; the first query does.
    engine = create_engine(settings.database_url)

    session_factory = create_session_factory(engine)

    def session_scope() -> AbstractAsyncContextManager[AsyncSession]:
        # Looked up on every call, so a test can put its own on `app.state`.
        return app.state.session_scope()

    mcp_server = create_mcp_server(settings, session_scope)
    mcp_app = mcp_asgi_app(mcp_server, settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        # The MCP endpoint only answers while its session manager runs.
        async with mcp_server.session_manager.run():
            yield
        await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    # What code outside a route (the MCP server) opens its sessions with.
    app.state.session_scope = lambda: transaction(session_factory)
    app.state.mcp_server = mcp_server
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
    # A plain route, not a mount: the MCP app sees the path unchanged and serves exactly
    # MCP_PATH, with its own bearer authentication in front.
    app.router.routes.append(Route(MCP_PATH, endpoint=mcp_app))
    return app
