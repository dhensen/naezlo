"""List grants: who has their own role on a list. List admins only."""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from todolist.api.deps import ListAdminContextDep
from todolist.api.project_grants import GrantOut, grant_out
from todolist.db import SessionDep
from todolist.models import ListRole, PrincipalKind
from todolist.services.list_grants import (
    ListGrantView,
    list_list_grants,
    revoke_list_grant,
    set_list_grant,
)
from todolist.services.project_grants import list_project_grants

router = APIRouter(prefix="/lists/{list_id}/grants", tags=["list grants"])


class ListGrantIn(BaseModel):
    principal_kind: PrincipalKind
    principal_id: uuid.UUID
    # `none` hides the list from the principal, whatever their role on the project.
    role: ListRole


class ListGrantOut(BaseModel):
    id: uuid.UUID
    principal_kind: PrincipalKind
    principal_id: uuid.UUID
    name: str
    email: str | None
    role: ListRole
    created_at: datetime
    updated_at: datetime


def _grant_out(view: ListGrantView) -> ListGrantOut:
    return ListGrantOut(
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
async def list_grants_route(ctx: ListAdminContextDep, session: SessionDep) -> list[ListGrantOut]:
    return [_grant_out(view) for view in await list_list_grants(session, ctx.todo_list)]


@router.get("/inherited")
async def list_inherited_grants_route(
    ctx: ListAdminContextDep, session: SessionDep
) -> list[GrantOut]:
    """The grants on the list's project: the role of everyone without a grant on the list itself.

    A list admin may read them without a role on the project, to see who else gets in.
    """
    return [grant_out(view) for view in await list_project_grants(session, ctx.project)]


@router.put("")
async def set_grant_route(
    body: ListGrantIn, ctx: ListAdminContextDep, session: SessionDep
) -> ListGrantOut:
    view = await set_list_grant(
        session,
        ctx.principal,
        ctx.todo_list,
        ctx.project,
        body.principal_kind,
        body.principal_id,
        body.role,
    )
    return _grant_out(view)


@router.delete("/{grant_id}", status_code=204)
async def revoke_grant_route(
    grant_id: uuid.UUID, ctx: ListAdminContextDep, session: SessionDep
) -> None:
    await revoke_list_grant(session, ctx.principal, ctx.todo_list, grant_id)
