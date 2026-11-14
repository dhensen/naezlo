"""List grants: give users and agents of the organization their own role on one list.

The callers check that the acting principal is admin on the list (`ListAdminContextDep`).
A list grant replaces the principal's project role on that list (`todolist.permissions`).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import NotFoundError
from todolist.models import Agent, ListGrant, ListRole, PrincipalKind, Project, TodoList, User
from todolist.services.project_grants import find_grantable_principal


@dataclass(frozen=True)
class ListGrantView:
    """A list grant with the display data of its principal."""

    grant: ListGrant
    principal_id: uuid.UUID
    name: str
    # Users only; an agent has no email address.
    email: str | None


def _view(grant: ListGrant, user: User | None, agent: Agent | None) -> ListGrantView:
    if user is not None:
        return ListGrantView(grant=grant, principal_id=user.id, name=user.name, email=user.email)
    # The check constraint on list_grants guarantees one of the two.
    assert agent is not None
    return ListGrantView(grant=grant, principal_id=agent.id, name=agent.name, email=None)


async def list_list_grants(session: AsyncSession, todo_list: TodoList) -> list[ListGrantView]:
    """The grants on the list itself (not the inherited project roles), oldest first."""
    rows = await session.execute(
        select(ListGrant, User, Agent)
        .outerjoin(User, User.id == ListGrant.user_id)
        .outerjoin(Agent, Agent.id == ListGrant.agent_id)
        .where(ListGrant.list_id == todo_list.id)
        .order_by(ListGrant.id)
    )
    return [_view(grant, user, agent) for grant, user, agent in rows]


async def set_list_grant(
    session: AsyncSession,
    todo_list: TodoList,
    project: Project,
    kind: PrincipalKind,
    principal_id: uuid.UUID,
    role: ListRole,
) -> ListGrantView:
    """Give the user or agent `role` on the list, replacing the list grant they had.

    `project` is the list's project. 422 `invalid_principal` unless the user is a member of
    its organization or the agent belongs to it.
    """
    if todo_list.project_id != project.id:
        raise ValueError("project is not the list's project")
    user, agent = await find_grantable_principal(
        session, project.organization_id, kind, principal_id
    )
    principal_column = ListGrant.user_id if user is not None else ListGrant.agent_id
    existing = select(ListGrant).where(
        ListGrant.list_id == todo_list.id, principal_column == principal_id
    )
    grant = await session.scalar(existing)
    if grant is None:
        try:
            async with session.begin_nested():
                grant = ListGrant(
                    list_id=todo_list.id,
                    principal_kind=kind,
                    user_id=principal_id if user is not None else None,
                    agent_id=principal_id if agent is not None else None,
                    role=role,
                )
                session.add(grant)
                await session.flush()
        except IntegrityError:
            # Someone granted the same principal at the same moment: change that grant instead.
            grant = (await session.scalars(existing)).one()
    if grant.role is not role:
        grant.role = role
        await session.flush()
    # updated_at is set by the database.
    await session.refresh(grant)
    return _view(grant, user, agent)


async def revoke_list_grant(
    session: AsyncSession, todo_list: TodoList, grant_id: uuid.UUID
) -> None:
    """Delete a grant of this list. 404 for an unknown id or a grant of another list.

    The principal falls back to their role on the project, if they have one.
    """
    grant = await session.scalar(
        select(ListGrant).where(ListGrant.id == grant_id, ListGrant.list_id == todo_list.id)
    )
    if grant is None:
        raise NotFoundError("Grant not found")
    await session.delete(grant)
    await session.flush()
