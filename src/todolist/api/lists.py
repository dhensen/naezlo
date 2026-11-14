"""Lists: created and listed in a project, then addressed by their own id.

Access follows the caller's role on the list and the list mode (`list_access` in
`todolist.permissions`): reading needs viewer, changing editor (admin when the list is
AI-only), deleting admin. Creating needs editor on the project; the index of a project gives
the lists the caller can see.
"""

import uuid
from dataclasses import replace
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.api.deps import (
    ListAdminContextDep,
    ListContextDep,
    ListEditorContextDep,
    ProjectEditorContextDep,
    ProjectListsContextDep,
)
from todolist.db import SessionDep
from todolist.errors import NotFoundError
from todolist.models import ListMode, Project, ProjectRole, TodoList
from todolist.permissions import ListAccess, ListAction, list_access, list_accesses
from todolist.principals import Principal
from todolist.services.items import count_items
from todolist.services.lists import create_list, delete_list, update_list

project_router = APIRouter(prefix="/projects/{project_id}/lists", tags=["lists"])
router = APIRouter(prefix="/lists/{list_id}", tags=["lists"])

# todo_lists.name holds 200 characters.
ListName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ListDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ListIn(BaseModel):
    name: ListName
    description: ListDescription | None = None
    # Left out or null: mixed when the organization has an agent, otherwise human_only.
    mode: ListMode | None = None


class ListPatch(BaseModel):
    """Only the fields that are sent change. `description: null` removes the description."""

    name: ListName | None = None
    description: ListDescription | None = None
    mode: ListMode | None = None

    @field_validator("name", "mode")
    @classmethod
    def _is_not_null(cls, value: object) -> object:
        # Runs only when the field is sent: leaving it out is fine, null is not a value.
        if value is None:
            raise ValueError("cannot be null")
        return value


class ListOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    # For a caller who can open the list but not its project.
    project_name: str
    # The list's page lives under its organization's address.
    organization_id: uuid.UUID
    name: str
    description: str | None
    mode: ListMode
    position: int
    # Items that are not done yet.
    open_item_count: int
    # The caller's effective role on the list, and what they may do with it (the role and
    # the list mode together): what the UI may offer.
    role: ProjectRole
    actions: list[ListAction]
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _list_out(
    todo_list: TodoList, project: Project, access: ListAccess, open_item_count: int
) -> ListOut:
    return ListOut(
        id=todo_list.id,
        project_id=todo_list.project_id,
        project_name=project.name,
        organization_id=project.organization_id,
        name=todo_list.name,
        description=todo_list.description,
        mode=todo_list.mode,
        position=todo_list.position,
        open_item_count=open_item_count,
        role=access.role,
        actions=access.actions,
        created_by=todo_list.created_by,
        created_at=todo_list.created_at,
        updated_at=todo_list.updated_at,
    )


async def _open_item_count(session: AsyncSession, todo_list: TodoList) -> int:
    return (await count_items(session, [todo_list.id]))[todo_list.id].open


@project_router.get("")
async def list_lists_route(ctx: ProjectListsContextDep, session: SessionDep) -> list[ListOut]:
    principal = Principal.for_user(ctx.user, ctx.project.organization_id)
    accesses = await list_accesses(session, principal, ctx.project, ctx.todo_lists)
    counts = await count_items(session, [todo_list.id for todo_list in ctx.todo_lists])
    return [
        _list_out(todo_list, ctx.project, accesses[todo_list.id], counts[todo_list.id].open)
        for todo_list in ctx.todo_lists
        if todo_list.id in accesses
    ]


@project_router.post("", status_code=201)
async def create_list_route(
    body: ListIn, ctx: ProjectEditorContextDep, session: SessionDep
) -> ListOut:
    todo_list = await create_list(
        session, ctx.principal, ctx.project, body.name, body.description, body.mode
    )
    access = await list_access(session, ctx.principal, todo_list, ctx.project)
    if access is None:
        # Cannot happen for a user who may create lists here; never answer without a role.
        raise NotFoundError("List not found")
    return _list_out(todo_list, ctx.project, access, 0)


@router.get("")
async def get_list_route(ctx: ListContextDep, session: SessionDep) -> ListOut:
    return _list_out(
        ctx.todo_list, ctx.project, ctx.access, await _open_item_count(session, ctx.todo_list)
    )


@router.patch("")
async def update_list_route(
    body: ListPatch, ctx: ListEditorContextDep, session: SessionDep
) -> ListOut:
    todo_list = await update_list(
        session,
        ctx.principal,
        ctx.todo_list,
        name=body.name,
        description=body.description,
        set_description="description" in body.model_fields_set,
        mode=body.mode,
    )
    # A new mode changes what the caller may do from here on.
    access = replace(ctx.access, mode=todo_list.mode)
    return _list_out(todo_list, ctx.project, access, await _open_item_count(session, todo_list))


@router.delete("", status_code=204)
async def delete_list_route(ctx: ListAdminContextDep, session: SessionDep) -> None:
    await delete_list(session, ctx.principal, ctx.todo_list)
