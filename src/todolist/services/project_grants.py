"""Project grants: share a project with users and agents of its organization.

The callers check that the acting principal is admin on the project
(`ProjectAdminContextDep`). The rules that depend on the target are applied here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import AppError, ConflictError, NotFoundError
from todolist.models import (
    Agent,
    Membership,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
    User,
)
from todolist.permissions import project_stays_administrable


@dataclass(frozen=True)
class GrantView:
    """A grant with the display data of its principal."""

    grant: ProjectGrant
    principal_id: uuid.UUID
    name: str
    # Users only; an agent has no email address.
    email: str | None


def _view(grant: ProjectGrant, user: User | None, agent: Agent | None) -> GrantView:
    if user is not None:
        return GrantView(grant=grant, principal_id=user.id, name=user.name, email=user.email)
    # The check constraint on project_grants guarantees one of the two.
    assert agent is not None
    return GrantView(grant=grant, principal_id=agent.id, name=agent.name, email=None)


async def list_project_grants(session: AsyncSession, project: Project) -> list[GrantView]:
    """The grants on the project, oldest first."""
    rows = await session.execute(
        select(ProjectGrant, User, Agent)
        .outerjoin(User, User.id == ProjectGrant.user_id)
        .outerjoin(Agent, Agent.id == ProjectGrant.agent_id)
        .where(ProjectGrant.project_id == project.id)
        .order_by(ProjectGrant.id)
    )
    return [_view(grant, user, agent) for grant, user, agent in rows]


def _invalid_principal(kind: PrincipalKind) -> AppError:
    detail = (
        "The user is not a member of the project's organization"
        if kind is PrincipalKind.USER
        else "The agent does not belong to the project's organization"
    )
    return AppError(422, "invalid_principal", detail)


async def _ensure_stays_administrable(
    session: AsyncSession, project: Project, grant: ProjectGrant
) -> None:
    """Raise 409 when `grant` is the last way a person administers the project.

    Call it before the admin grant of a user is revoked or downgraded. The project row is
    locked, so two admins who revoke each other at the same moment can't both pass.
    """
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    if not await project_stays_administrable(session, project, without=grant):
        raise ConflictError(
            "last_project_admin",
            "A project needs someone who can administer it; make someone else admin first",
        )


def _is_user_admin_grant(grant: ProjectGrant) -> bool:
    return grant.principal_kind is PrincipalKind.USER and grant.role is ProjectRole.ADMIN


async def set_project_grant(
    session: AsyncSession,
    project: Project,
    kind: PrincipalKind,
    principal_id: uuid.UUID,
    role: ProjectRole,
) -> GrantView:
    """Give the user or agent `role` on the project, replacing the role they had.

    422 `invalid_principal` unless the user is a member of the project's organization or the
    agent belongs to it; 409 `last_project_admin` when a downgrade would leave the project
    without anyone to administer it.
    """
    user: User | None = None
    agent: Agent | None = None
    if kind is PrincipalKind.USER:
        user = await session.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(User.id == principal_id, Membership.organization_id == project.organization_id)
        )
        principal_column = ProjectGrant.user_id
    else:
        agent = await session.scalar(
            select(Agent).where(
                Agent.id == principal_id, Agent.organization_id == project.organization_id
            )
        )
        principal_column = ProjectGrant.agent_id
    if user is None and agent is None:
        raise _invalid_principal(kind)

    existing = select(ProjectGrant).where(
        ProjectGrant.project_id == project.id, principal_column == principal_id
    )
    grant = await session.scalar(existing)
    if grant is None:
        try:
            async with session.begin_nested():
                grant = ProjectGrant(
                    project_id=project.id,
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
        if _is_user_admin_grant(grant):
            await _ensure_stays_administrable(session, project, grant)
        grant.role = role
        await session.flush()
    # updated_at is set by the database.
    await session.refresh(grant)
    return _view(grant, user, agent)


async def revoke_project_grant(
    session: AsyncSession, project: Project, grant_id: uuid.UUID
) -> None:
    """Delete a grant of this project. 404 for an unknown id or a grant of another project."""
    grant = await session.scalar(
        select(ProjectGrant).where(
            ProjectGrant.id == grant_id, ProjectGrant.project_id == project.id
        )
    )
    if grant is None:
        raise NotFoundError("Grant not found")
    if _is_user_admin_grant(grant):
        await _ensure_stays_administrable(session, project, grant)
    await session.delete(grant)
    await session.flush()
