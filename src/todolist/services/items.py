"""Items: list, add, change, complete, move and delete the items of a list.

Shared by the HTTP API and the MCP tools. The callers check the acting principal's role on
the list and the list mode (`list_access` in `todolist.permissions`).
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from typing import Annotated

from pydantic import StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import AppError
from todolist.models import AuditAction, Item, ItemStatus, TodoList
from todolist.principals import Principal
from todolist.services.audit import changes, record_event

# What a caller (HTTP API, MCP tools) accepts as an item's title and notes. items.title holds
# 500 characters.
ItemTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ItemNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]


def _clean_notes(notes: str | None) -> str | None:
    """Trimmed; empty notes are stored as no notes."""
    if notes is None:
        return None
    return notes.strip() or None


async def _lock_list(session: AsyncSession, list_id: uuid.UUID) -> None:
    """Make other transactions that change the positions of this list wait for this one.

    Everything that picks or changes a position (create, move, delete) takes this lock first,
    so the positions stay 1, 2, 3, ... when two of them happen at the same moment.
    """
    await session.execute(select(TodoList.id).where(TodoList.id == list_id).with_for_update())


async def _shift_positions(
    session: AsyncSession, list_id: uuid.UUID, first: int, last: int | None, by: int
) -> None:
    """Add `by` to the position of the list's items from position `first` up to and including
    `last` (to the end when None). The caller holds the list lock."""
    in_range = (Item.list_id == list_id) & (Item.position >= first)
    if last is not None:
        in_range &= Item.position <= last
    await session.execute(
        update(Item)
        .where(in_range)
        # Shifting an item is not a change to it: keep its updated_at.
        .values(position=Item.position + by, updated_at=Item.updated_at)
        .execution_options(synchronize_session="fetch")
    )


async def _record(
    session: AsyncSession,
    principal: Principal,
    action: AuditAction,
    item: Item,
    project_id: uuid.UUID | None = None,
    **details: object,
) -> None:
    """Record an event about the item. Call it before the item is deleted or expired."""
    if project_id is None:
        project_id = await session.scalar(
            select(TodoList.project_id).where(TodoList.id == item.list_id)
        )
    await record_event(
        session,
        principal,
        action,
        target_kind="item",
        target_id=item.id,
        project_id=project_id,
        list_id=item.list_id,
        # The title makes the event readable after the item is gone.
        details={"title": item.title, **details},
    )


async def list_items(
    session: AsyncSession, todo_list: TodoList, *, include_done: bool = True
) -> list[Item]:
    """The items of the list in their order (position, then age); only the open ones
    without `include_done`."""
    query = select(Item).where(Item.list_id == todo_list.id)
    if not include_done:
        query = query.where(Item.status == ItemStatus.OPEN)
    items = await session.scalars(query.order_by(Item.position, Item.id))
    return list(items)


@dataclass(frozen=True)
class ItemCounts:
    """How many items of a list are open and how many are done."""

    open: int = 0
    done: int = 0


async def count_items(
    session: AsyncSession, list_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, ItemCounts]:
    """The open and done item counts of each of the lists (zeros for a list without items).

    The caller has checked that the principal can read these lists.
    """
    counts = {list_id: ItemCounts() for list_id in list_ids}
    if not counts:
        return counts
    rows = await session.execute(
        select(
            Item.list_id,
            func.count().filter(Item.status == ItemStatus.OPEN),
            func.count().filter(Item.status == ItemStatus.DONE),
        )
        .where(Item.list_id.in_(counts))
        .group_by(Item.list_id)
    )
    for list_id, open_count, done_count in rows:
        counts[list_id] = ItemCounts(open=open_count, done=done_count)
    return counts


async def create_item(
    session: AsyncSession,
    principal: Principal,
    todo_list: TodoList,
    title: str,
    notes: str | None = None,
) -> Item:
    """Add an open item at the end of the list, created by `principal`."""
    # Two items created at the same moment must not get the same position.
    await _lock_list(session, todo_list.id)
    last = await session.scalar(select(func.max(Item.position)).where(Item.list_id == todo_list.id))
    item = Item(
        list_id=todo_list.id,
        title=title.strip(),
        notes=_clean_notes(notes),
        status=ItemStatus.OPEN,
        position=1 if last is None else last + 1,
        created_by_kind=principal.kind,
        created_by_id=principal.id,
    )
    session.add(item)
    await session.flush()
    await _record(session, principal, AuditAction.ITEM_CREATED, item, todo_list.project_id)
    return item


async def update_item(
    session: AsyncSession,
    principal: Principal,
    item: Item,
    *,
    title: str | None = None,
    notes: str | None = None,
    set_notes: bool = False,
    status: ItemStatus | None = None,
) -> Item:
    """Change the title and the status (when given) and the notes (when `set_notes`; None
    clears them).

    Going from open to done records `principal` and the time as the completion; going back to
    open clears both. Setting the status an item already has changes nothing: an item that is
    done keeps its first completion.

    The audit log gets `item.updated` for a changed title or notes and `item.completed` or
    `item.reopened` for a changed status (both when one call does both).
    """
    old = {"title": item.title, "notes": item.notes}
    status_action: AuditAction | None = None
    if title is not None:
        item.title = title.strip()
    if set_notes:
        item.notes = _clean_notes(notes)
    if status is not None and status is not item.status:
        item.status = status
        status_action = (
            AuditAction.ITEM_COMPLETED if status is ItemStatus.DONE else AuditAction.ITEM_REOPENED
        )
        if status is ItemStatus.DONE:
            item.completed_by_kind = principal.kind
            item.completed_by_id = principal.id
            # The database's clock, like created_at and updated_at.
            item.completed_at = func.now()
        else:
            item.completed_by_kind = None
            item.completed_by_id = None
            item.completed_at = None
    await session.flush()
    # updated_at and completed_at are set by the database.
    await session.refresh(item)
    changed = changes(old, {"title": item.title, "notes": item.notes})
    if changed:
        await _record(session, principal, AuditAction.ITEM_UPDATED, item, changes=changed)
    if status_action is not None:
        await _record(session, principal, status_action, item)
    return item


async def move_item(
    session: AsyncSession,
    principal: Principal,
    item: Item,
    before_item_id: uuid.UUID | None,
) -> Item:
    """Move the item to just before the item `before_item_id` of the same list, or to the end
    of the list when None. The items in between shift one place; the positions stay 1 to n.

    422 `invalid_before_item` when there is no such item in the item's list (it does not
    exist or it is in another list: the answer is the same, so it tells nothing about lists
    the caller cannot see). Moving an item before itself leaves it where it is.
    `principal` is the actor, for the audit log; an item that stays where it is records nothing.
    """
    await _lock_list(session, item.list_id)
    # The position as it is now that nobody else can change it.
    await session.refresh(item)
    old = item.position
    if before_item_id is None:
        count = await session.scalar(
            select(func.count()).select_from(Item).where(Item.list_id == item.list_id)
        )
        new = count or 1
    elif before_item_id == item.id:
        new = old
    else:
        before = await session.scalar(
            select(Item.position).where(Item.id == before_item_id, Item.list_id == item.list_id)
        )
        if before is None:
            raise AppError(422, "invalid_before_item", "before_item_id is not an item of this list")
        # Taking the item out moves everything after it one place up.
        new = before - 1 if before > old else before
    if new == old:
        return item
    if new > old:
        await _shift_positions(session, item.list_id, old + 1, new, -1)
    else:
        await _shift_positions(session, item.list_id, new, old - 1, +1)
    item.position = new
    await session.flush()
    await session.refresh(item)
    await _record(
        session,
        principal,
        AuditAction.ITEM_MOVED,
        item,
        changes={"position": {"old": old, "new": new}},
    )
    return item


async def delete_item(session: AsyncSession, principal: Principal, item: Item) -> None:
    """Remove the item and close the gap it leaves in the positions. `principal` is the actor,
    for the audit log."""
    list_id = item.list_id
    await _lock_list(session, list_id)
    await session.refresh(item)
    position = item.position
    await _record(session, principal, AuditAction.ITEM_DELETED, item)
    await session.delete(item)
    await session.flush()
    await _shift_positions(session, list_id, position + 1, None, -1)
