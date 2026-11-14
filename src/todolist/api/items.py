"""Items: listed and added in a list, then addressed by their own id.

Access follows the caller's role on the item's list (see `todolist.permissions`): reading
needs viewer, everything else (also moving) editor.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints, field_validator

from todolist.api.deps import (
    ItemContextDep,
    ItemEditorContextDep,
    ListContextDep,
    ListEditorContextDep,
)
from todolist.db import SessionDep
from todolist.models import Item, ItemStatus, PrincipalKind
from todolist.services.items import (
    create_item,
    delete_item,
    list_items,
    move_item,
    update_item,
)

list_router = APIRouter(prefix="/lists/{list_id}/items", tags=["items"])
router = APIRouter(prefix="/items/{item_id}", tags=["items"])

# items.title holds 500 characters.
ItemTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ItemNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]


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
    created_at: datetime
    updated_at: datetime


def _item_out(item: Item) -> ItemOut:
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
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@list_router.get("")
async def list_items_route(ctx: ListContextDep, session: SessionDep) -> list[ItemOut]:
    return [_item_out(item) for item in await list_items(session, ctx.todo_list)]


@list_router.post("", status_code=201)
async def create_item_route(
    body: ItemIn, ctx: ListEditorContextDep, session: SessionDep
) -> ItemOut:
    item = await create_item(session, ctx.principal, ctx.todo_list, body.title, body.notes)
    return _item_out(item)


@router.get("")
async def get_item_route(ctx: ItemContextDep) -> ItemOut:
    return _item_out(ctx.item)


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
    return _item_out(item)


@router.delete("", status_code=204)
async def delete_item_route(ctx: ItemEditorContextDep, session: SessionDep) -> None:
    await delete_item(session, ctx.principal, ctx.item)


@router.post("/move")
async def move_item_route(
    body: ItemMove, ctx: ItemEditorContextDep, session: SessionDep
) -> ItemOut:
    item = await move_item(session, ctx.principal, ctx.item, body.before_item_id)
    return _item_out(item)
