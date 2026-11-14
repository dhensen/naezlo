"""Audit log: record who changed what, and read it back.

The services that change projects, lists, items and grants call `record_event` after the
change, in the same transaction: an event exists only if the change was committed.
`project_events` and `list_events` read the log, newest first, one page at a time.
"""

import base64
import binascii
import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import AppError
from todolist.models import AuditAction, AuditEvent, PrincipalKind, Project, TodoList
from todolist.permissions import visible_lists
from todolist.principals import Principal

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _plain(value: object) -> object:
    """The value as it is stored in JSON."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def changes(old: Mapping[str, object], new: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """The fields of `old` whose value differs in `new`, as `{field: {"old": ..., "new": ...}}`."""
    return {
        field: {"old": _plain(value), "new": _plain(new[field])}
        for field, value in old.items()
        if new[field] != value
    }


async def record_event(
    session: AsyncSession,
    principal: Principal,
    action: AuditAction,
    *,
    target_kind: str,
    target_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    list_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Record that `principal` did `action` to the target, in the caller's transaction.

    The event belongs to the organization the principal acts in. It is flushed, not committed:
    when the request fails, the event is rolled back together with the change.
    """
    event = AuditEvent(
        organization_id=principal.organization_id,
        project_id=project_id,
        list_id=list_id,
        actor_kind=principal.kind,
        actor_id=principal.id,
        actor_name=principal.name,
        action=action.value,
        target_kind=target_kind,
        target_id=target_id,
        details=details or {},
    )
    session.add(event)
    await session.flush()
    return event


@dataclass(frozen=True)
class EventFilter:
    """Optional filters for reading the log. `action_prefix` matches the start of the action:
    "item." gives every item event, "item.completed" only that one."""

    actor_kind: PrincipalKind | None = None
    actor_id: uuid.UUID | None = None
    action_prefix: str | None = None


@dataclass(frozen=True)
class EventPage:
    events: list[AuditEvent]
    # Give it back as `cursor` for the next (older) page; None after the last page.
    next_cursor: str | None


def _encode_cursor(event: AuditEvent) -> str:
    raw = f"{event.created_at.isoformat()}|{event.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """The place in the log a cursor points at: the last event of the page before."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        created_at, _, event_id = raw.partition("|")
        decoded = datetime.fromisoformat(created_at), uuid.UUID(event_id)
    except (ValueError, binascii.Error) as error:
        raise AppError(422, "invalid_cursor", "Invalid cursor") from error
    if decoded[0].tzinfo is None:
        raise AppError(422, "invalid_cursor", "Invalid cursor")
    return decoded


async def _page(
    session: AsyncSession,
    scope: ColumnElement[bool],
    filters: EventFilter,
    limit: int,
    cursor: str | None,
) -> EventPage:
    """One page of the events in `scope`, newest first. Events of one transaction share their
    `created_at`; the id (UUIDv7) orders those."""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    order = tuple_(AuditEvent.created_at, AuditEvent.id)
    query = select(AuditEvent).where(scope)
    if filters.actor_kind is not None:
        query = query.where(AuditEvent.actor_kind == filters.actor_kind)
    if filters.actor_id is not None:
        query = query.where(AuditEvent.actor_id == filters.actor_id)
    if filters.action_prefix:
        query = query.where(AuditEvent.action.startswith(filters.action_prefix, autoescape=True))
    if cursor is not None:
        query = query.where(order < _decode_cursor(cursor))
    query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    # One more than asked for tells whether there is a next page.
    events = list(await session.scalars(query.limit(limit + 1)))
    if len(events) <= limit:
        return EventPage(events=events, next_cursor=None)
    events = events[:limit]
    return EventPage(events=events, next_cursor=_encode_cursor(events[-1]))


async def project_events(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    filters: EventFilter | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> EventPage:
    """The events of the project, its lists and their items, newest first.

    The caller has checked that the principal is an admin of the project. Events of a list
    the principal cannot see (a list grant `none`, or human-only for an agent) are left out;
    events of deleted lists are part of the project's history and stay.
    """
    lists_of_project = select(TodoList.id).where(TodoList.project_id == project.id)
    visible = select(visible_lists(principal, project).subquery().c.id)
    scope = (AuditEvent.project_id == project.id) & or_(
        AuditEvent.list_id.is_(None),
        AuditEvent.list_id.in_(visible),
        AuditEvent.list_id.not_in(lists_of_project),
    )
    return await _page(session, scope, filters or EventFilter(), limit, cursor)


async def list_events(
    session: AsyncSession,
    todo_list: TodoList,
    *,
    filters: EventFilter | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
) -> EventPage:
    """The events of the list and its items, newest first. The caller has checked that the
    principal is an admin of the list."""
    scope = AuditEvent.list_id == todo_list.id
    return await _page(session, scope, filters or EventFilter(), limit, cursor)
