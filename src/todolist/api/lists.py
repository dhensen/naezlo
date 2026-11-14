"""Lists: created and listed in a project, then addressed by their own id.

Access follows the caller's role on the list (see `todolist.permissions`): reading needs
viewer, changing editor, deleting admin. Creating needs editor on the project; the index of a
project gives the lists the caller can see.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints, field_validator

from todolist.api.deps import (
    ListAdminContextDep,
    ListContextDep,
    ListEditorContextDep,
    ProjectEditorContextDep,
    ProjectListsContextDep,
)
from todolist.db import SessionDep
from todolist.models import ListMode, Project, TodoList
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
    name: str
    description: str | None
    mode: ListMode
    position: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


def _list_out(todo_list: TodoList, project: Project) -> ListOut:
    return ListOut(
        id=todo_list.id,
        project_id=todo_list.project_id,
        project_name=project.name,
        name=todo_list.name,
        description=todo_list.description,
        mode=todo_list.mode,
        position=todo_list.position,
        created_by=todo_list.created_by,
        created_at=todo_list.created_at,
        updated_at=todo_list.updated_at,
    )


@project_router.get("")
async def list_lists_route(ctx: ProjectListsContextDep) -> list[ListOut]:
    return [_list_out(todo_list, ctx.project) for todo_list in ctx.todo_lists]


@project_router.post("", status_code=201)
async def create_list_route(
    body: ListIn, ctx: ProjectEditorContextDep, session: SessionDep
) -> ListOut:
    todo_list = await create_list(
        session, ctx.principal, ctx.project, body.name, body.description, body.mode
    )
    return _list_out(todo_list, ctx.project)


@router.get("")
async def get_list_route(ctx: ListContextDep) -> ListOut:
    return _list_out(ctx.todo_list, ctx.project)


@router.patch("")
async def update_list_route(
    body: ListPatch, ctx: ListEditorContextDep, session: SessionDep
) -> ListOut:
    todo_list = await update_list(
        session,
        ctx.todo_list,
        name=body.name,
        description=body.description,
        set_description="description" in body.model_fields_set,
        mode=body.mode,
    )
    return _list_out(todo_list, ctx.project)


@router.delete("", status_code=204)
async def delete_list_route(ctx: ListAdminContextDep, session: SessionDep) -> None:
    await delete_list(session, ctx.todo_list)
