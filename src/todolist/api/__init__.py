"""HTTP API routers, all under `/api`."""

from fastapi import APIRouter

from todolist.api import agents, auth, config, invitations, me, members, orgs, projects

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(config.router)
api_router.include_router(me.router)
api_router.include_router(orgs.router)
api_router.include_router(members.router)
api_router.include_router(invitations.router)
api_router.include_router(agents.router)
api_router.include_router(projects.org_router)
api_router.include_router(projects.router)

__all__ = ["api_router"]
