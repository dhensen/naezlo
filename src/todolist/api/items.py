"""Items: listed and added in a list, then addressed by their own id.

Access follows the caller's role on the item's list and the list mode (`list_access` in
`todolist.permissions`): reading needs viewer, everything else (also moving) editor. In an
AI-only list people only read: changing anything is a 403 `list_ai_only`.

An item can be assigned to anyone who may change the items of its list (`/assignee`, and
`GET /api/lists/{id}/assignees` for who that is). In a list with `assignment_required` only
the assignee can complete an item (409 `item_not_assigned` / `item_assigned_to_other`).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.api.deps import (
    ItemContext,
    ItemContextDep,
    ItemEditorContextDep,
    ListContext,
    ListContextDep,
    ListItemEditorContextDep,
)
from todolist.db import SessionDep
from todolist.models import Item, ItemStatus, PrincipalKind
from todolist.permissions import assignable_principals
from todolist.principals import Principal
from todolist.services.items import (
    ItemNotes,
    ItemTitle,
    assign_item,
    create_item,
    delete_item,
    item_assignees,
    list_items,
    move_item,
    unassign_item,
    update_item,
)

list_router = APIRouter(prefix="/lists/{list_id}/items", tags=["items"])
assignees_router = APIRouter(prefix="/lists/{list_id}/assignees", tags=["items"])
router = APIRouter(prefix="/items/{item_id}", tags=["items"])


class ItemIn(BaseModel):
    title: ItemTitle
    notes: ItemNotes | None = None


class ItemPatch(BaseModel):
    """Only the fields that are sent change. `notes: null` removes the notes."""

    title: ItemTitle | None = None
    notes: ItemNotes | None = None
    status: ItemStatus | None = None

    @field_validator("title", "status")
    @classmethod
    def _is_not_null(cls, value: object) -> object:
        # Runs only when the field is sent: leaving it out is fine, null is not a value.
        if value is None:
            raise ValueError("cannot be null")
        return value


class ItemMove(BaseModel):
    """Where the item goes: before this item of the same list, or to the end when null. The
    field must be sent, so an empty body does not move anything."""

    before_item_id: uuid.UUID | None


class ActorOut(BaseModel):
    """Who did something: a user or an agent."""

    kind: PrincipalKind
    id: uuid.UUID


class AssigneeIn(BaseModel):
    """The user or agent to assign the item to."""

    kind: PrincipalKind
    id: uuid.UUID


class AssigneeOut(BaseModel):
    """Someone an item is or can be assigned to."""

    kind: PrincipalKind
    id: uuid.UUID
    name: str


class ItemOut(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID
    title: str
    notes: str | None
    status: ItemStatus
    position: int
    created_by: ActorOut
    completed_by: ActorOut | None
    completed_at: datetime | None
    # Who works on the item; null when nobody does (or they lost access to the list).
    assignee: AssigneeOut | None
    created_at: datetime
    updated_at: datetime


def _assignee_out(principal: Principal) -> AssigneeOut:
    return AssigneeOut(kind=principal.kind, id=principal.id, name=principal.name)


def _item_out(item: Item, assignee: Principal | None) -> ItemOut:
    completed_by = (
        None
        if item.completed_by_kind is None or item.completed_by_id is None
        else ActorOut(kind=item.completed_by_kind, id=item.completed_by_id)
    )
    return ItemOut(
        id=item.id,
        list_id=item.list_id,
        title=item.title,
        notes=item.notes,
        status=item.status,
        position=item.position,
        created_by=ActorOut(kind=item.created_by_kind, id=item.created_by_id),
        completed_by=completed_by,
        completed_at=item.completed_at,
        assignee=None if assignee is None else _assignee_out(assignee),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _one_out(session: AsyncSession, ctx: ItemContext | ListContext, item: Item) -> ItemOut:
    """The item as the API gives it, with its assignee looked up."""
    assignees = await item_assignees(session, ctx.todo_list, ctx.project, [item])
    return _item_out(item, assignees.get(item.id))


@list_router.get("")
async def list_items_route(ctx: ListContextDep, session: SessionDep) -> list[ItemOut]:
    items = await list_items(session, ctx.todo_list)
    assignees = await item_assignees(session, ctx.todo_list, ctx.project, items)
    return [_item_out(item, assignees.get(item.id)) for item in items]


@list_router.post("", status_code=201)
async def create_item_route(
    body: ItemIn, ctx: ListItemEditorContextDep, session: SessionDep
) -> ItemOut:
    item = await create_item(session, ctx.principal, ctx.todo_list, body.title, body.notes)
    return _item_out(item, None)


@assignees_router.get("")
async def list_assignees_route(ctx: ListContextDep, session: SessionDep) -> list[AssigneeOut]:
    """Everyone an item of the list can be assigned to: people first, each kind by name."""
    principals = await assignable_principals(session, ctx.todo_list, ctx.project)
    return [_assignee_out(principal) for principal in principals]


@router.get("")
async def get_item_route(ctx: ItemContextDep, session: SessionDep) -> ItemOut:
    return await _one_out(session, ctx, ctx.item)


@router.patch("")
async def update_item_route(
    body: ItemPatch, ctx: ItemEditorContextDep, session: SessionDep
) -> ItemOut:
    item = await update_item(
        session,
        ctx.principal,
        ctx.item,
        title=body.title,
        notes=body.notes,
        set_notes="notes" in body.model_fields_set,
        status=body.status,
    )
    return await _one_out(session, ctx, item)


@router.delete("", status_code=204)
async def delete_item_route(ctx: ItemEditorContextDep, session: SessionDep) -> None:
    await delete_item(session, ctx.principal, ctx.item)


@router.post("/move")
async def move_item_route(
    body: ItemMove, ctx: ItemEditorContextDep, session: SessionDep
) -> ItemOut:
    item = await move_item(session, ctx.principal, ctx.item, body.before_item_id)
    return await _one_out(session, ctx, item)


@router.put("/assignee")
async def assign_item_route(
    body: AssigneeIn, ctx: ItemEditorContextDep, session: SessionDep
) -> ItemOut:
    """Assign the item to a user or agent, in place of its assignee. 422 `invalid_assignee`
    when they cannot change the items of the list."""
    item = await assign_item(
        session, ctx.principal, ctx.item, ctx.todo_list, ctx.project, body.kind, body.id
    )
    return await _one_out(session, ctx, item)


@router.delete("/assignee")
async def unassign_item_route(ctx: ItemEditorContextDep, session: SessionDep) -> ItemOut:
    """Take the assignee off the item."""
    item = await unassign_item(session, ctx.principal, ctx.item)
    return await _one_out(session, ctx, item)
