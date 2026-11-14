"""HTTP API routers, all under `/api`."""

from fastapi import APIRouter

from todolist.api import (
    agents,
    auth,
    config,
    invitations,
    list_grants,
    lists,
    me,
    members,
    orgs,
    project_grants,
    projects,
)

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
api_router.include_router(project_grants.router)
api_router.include_router(lists.project_router)
api_router.include_router(lists.router)
api_router.include_router(list_grants.router)

__all__ = ["api_router"]
