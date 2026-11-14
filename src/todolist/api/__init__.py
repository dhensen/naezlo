"""HTTP API routers, all under `/api`."""

from fastapi import APIRouter

from todolist.api import auth, config, me, orgs

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(config.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)

__all__ = ["api_router"]
