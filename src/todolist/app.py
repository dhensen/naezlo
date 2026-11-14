"""FastAPI application factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from todolist.config import Settings, get_settings
from todolist.db import create_engine, create_session_factory

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
    app.include_router(health_router)
    return app
