"""Project grants: who a project is shared with. Project admins only."""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from naezlo.api.deps import ProjectAdminContextDep
from naezlo.db import SessionDep
from naezlo.models import PrincipalKind, ProjectRole
from naezlo.services.project_grants import (
    GrantView,
    list_project_grants,
    revoke_project_grant,
    set_project_grant,
)

router = APIRouter(prefix="/projects/{project_id}/grants", tags=["project grants"])


class GrantIn(BaseModel):
    principal_kind: PrincipalKind
    principal_id: uuid.UUID
    role: ProjectRole


class GrantOut(BaseModel):
    id: uuid.UUID
    principal_kind: PrincipalKind
    principal_id: uuid.UUID
    name: str
    email: str | None
    role: ProjectRole
    created_at: datetime
    updated_at: datetime


def grant_out(view: GrantView) -> GrantOut:
    return GrantOut(
        id=view.grant.id,
        principal_kind=view.grant.principal_kind,
        principal_id=view.principal_id,
        name=view.name,
        email=view.email,
        role=view.grant.role,
        created_at=view.grant.created_at,
        updated_at=view.grant.updated_at,
    )


@router.get("")
async def list_grants_route(ctx: ProjectAdminContextDep, session: SessionDep) -> list[GrantOut]:
    return [grant_out(view) for view in await list_project_grants(session, ctx.project)]


@router.put("")
async def set_grant_route(
    body: GrantIn, ctx: ProjectAdminContextDep, session: SessionDep
) -> GrantOut:
    view = await set_project_grant(
        session, ctx.principal, ctx.project, body.principal_kind, body.principal_id, body.role
    )
    return grant_out(view)


@router.delete("/{grant_id}", status_code=204)
async def revoke_grant_route(
    grant_id: uuid.UUID, ctx: ProjectAdminContextDep, session: SessionDep
) -> None:
    await revoke_project_grant(session, ctx.principal, ctx.project, grant_id)
