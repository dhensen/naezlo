"""Audit log: record who changed what.

The services that change projects, lists, items and grants call `record_event` after the
change, in the same transaction: an event exists only if the change was committed.
"""

import enum
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import AuditAction, AuditEvent
from todolist.principals import Principal


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
