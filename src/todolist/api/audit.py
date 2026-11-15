"""Audit log: what happened in a project or a list, newest first. Admins only.

Both routes page with a cursor: `next_cursor` of one answer is the `cursor` of the next request,
and is null on the last page.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from todolist.api.deps import ListAdminContextDep, ProjectAdminContextDep
from todolist.db import SessionDep
from todolist.models import AuditEvent, PrincipalKind
from todolist.services.audit import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ActionGroup,
    EventFilter,
    EventPage,
    list_events,
    project_events,
)

project_router = APIRouter(prefix="/projects/{project_id}/audit", tags=["audit"])
list_router = APIRouter(prefix="/lists/{list_id}/audit", tags=["audit"])


class AuditQuery(BaseModel):
    limit: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None
    actor_kind: PrincipalKind | None = None
    actor_id: uuid.UUID | None = None
    # The start of the action: "item." for every item event.
    action: str | None = Field(None, max_length=100)
    # All actions of one kind: items, lists (with the project's own events) or sharing (grants).
    group: ActionGroup | None = None

    @property
    def filters(self) -> EventFilter:
        return EventFilter(
            actor_kind=self.actor_kind,
            actor_id=self.actor_id,
            action_prefix=self.action,
            group=self.group,
        )


AuditQueryDep = Annotated[AuditQuery, Query()]


class AuditActorOut(BaseModel):
    kind: PrincipalKind
    id: uuid.UUID
    # The name when it happened.
    name: str


class AuditEventOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor: AuditActorOut
    action: str
    target_kind: str
    target_id: uuid.UUID
    project_id: uuid.UUID | None
    list_id: uuid.UUID | None
    details: dict[str, Any]


class AuditPageOut(BaseModel):
    events: list[AuditEventOut]
    next_cursor: str | None


def _event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=event.id,
        created_at=event.created_at,
        actor=AuditActorOut(kind=event.actor_kind, id=event.actor_id, name=event.actor_name),
        action=event.action,
        target_kind=event.target_kind,
        target_id=event.target_id,
        project_id=event.project_id,
        list_id=event.list_id,
        details=event.details,
    )


def _page_out(page: EventPage) -> AuditPageOut:
    return AuditPageOut(
        events=[_event_out(event) for event in page.events], next_cursor=page.next_cursor
    )


@project_router.get("")
async def project_audit_route(
    ctx: ProjectAdminContextDep, query: AuditQueryDep, session: SessionDep
) -> AuditPageOut:
    page = await project_events(
        session,
        ctx.principal,
        ctx.project,
        filters=query.filters,
        limit=query.limit,
        cursor=query.cursor,
    )
    return _page_out(page)


@list_router.get("")
async def list_audit_route(
    ctx: ListAdminContextDep, query: AuditQueryDep, session: SessionDep
) -> AuditPageOut:
    page = await list_events(
        session, ctx.todo_list, filters=query.filters, limit=query.limit, cursor=query.cursor
    )
    return _page_out(page)
