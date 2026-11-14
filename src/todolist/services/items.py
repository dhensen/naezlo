"""Items: list, add, change, complete and delete the items of a list.

Shared by the HTTP API and the MCP tools. The callers check the acting principal's role on
the list (`require_list_role` / `require_item_role`, see `todolist.permissions`).
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Item, ItemStatus, TodoList
from todolist.principals import Principal


def _clean_notes(notes: str | None) -> str | None:
    """Trimmed; empty notes are stored as no notes."""
    if notes is None:
        return None
    return notes.strip() or None


async def list_items(session: AsyncSession, todo_list: TodoList) -> list[Item]:
    """The items of the list in their order (position, then age)."""
    items = await session.scalars(
        select(Item).where(Item.list_id == todo_list.id).order_by(Item.position, Item.id)
    )
    return list(items)


async def create_item(
    session: AsyncSession,
    principal: Principal,
    todo_list: TodoList,
    title: str,
    notes: str | None = None,
) -> Item:
    """Add an open item at the end of the list, created by `principal`."""
    # Two items created at the same moment must not get the same position.
    await session.execute(select(TodoList.id).where(TodoList.id == todo_list.id).with_for_update())
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
    """
    if title is not None:
        item.title = title.strip()
    if set_notes:
        item.notes = _clean_notes(notes)
    if status is not None and status is not item.status:
        item.status = status
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
    return item


async def delete_item(session: AsyncSession, principal: Principal, item: Item) -> None:
    """Remove the item. `principal` is the actor, for the audit log."""
    del principal  # recorded once audit events exist
    await session.delete(item)
    await session.flush()
