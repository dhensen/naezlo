"""FastAPI application factory."""

from fastapi import APIRouter, FastAPI

from todolist.config import Settings, get_settings

health_router = APIRouter(tags=["health"])


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.include_router(health_router)
    return app
