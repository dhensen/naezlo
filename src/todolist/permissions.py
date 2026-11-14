"""The permission service: which role a principal has on a project.

Every permission check goes through here with a `Principal` (a user or an agent). Routes use
the dependencies built on it (`require_project_role` in `todolist.api.deps`); MCP tools call
these functions directly.

Rules (DECISIONS.md, "ACL"):
- Owners and admins of the project's organization are admin on every project in it.
- Everyone else has the role of their grant on the project, or no role at all.
- No role means the project does not exist for that principal (the caller answers 404).
"""

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import (
    Membership,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
)
from todolist.principals import Principal
from todolist.services.organizations import can_manage_organization

_RANK = {ProjectRole.VIEWER: 1, ProjectRole.EDITOR: 2, ProjectRole.ADMIN: 3}


def role_at_least(role: ProjectRole | None, minimum: ProjectRole) -> bool:
    """Whether `role` is `minimum` or higher. No role is never enough."""
    return role is not None and _RANK[role] >= _RANK[minimum]


async def effective_project_role(
    session: AsyncSession, principal: Principal, project: Project
) -> ProjectRole | None:
    """The principal's role on the project; None when the project does not exist for them.

    A user must (still) be a member of the project's organization and an agent must belong to
    it: a grant alone gives nothing. This is looked up here, so the caller does not have to
    have checked the membership before building the principal.
    """
    if principal.organization_id != project.organization_id:
        return None
    if principal.kind is PrincipalKind.AGENT:
        # `Principal.for_agent` takes the organization from the agent itself.
        return await session.scalar(
            select(ProjectGrant.role).where(
                ProjectGrant.project_id == project.id, ProjectGrant.agent_id == principal.id
            )
        )
    row = (
        await session.execute(
            select(Membership.role, ProjectGrant.role)
            .outerjoin(
                ProjectGrant,
                and_(
                    ProjectGrant.project_id == project.id,
                    ProjectGrant.user_id == Membership.user_id,
                ),
            )
            .where(
                Membership.organization_id == project.organization_id,
                Membership.user_id == principal.id,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    membership_role, grant_role = row
    if can_manage_organization(membership_role):
        return ProjectRole.ADMIN
    return grant_role


def visible_projects(principal: Principal) -> Select[Project]:
    """A query for the projects of the principal's organization that the principal has a role on.

    The same rules as `effective_project_role`, for a whole organization at once.
    """
    in_organization = select(Project).where(Project.organization_id == principal.organization_id)
    if principal.kind is PrincipalKind.AGENT:
        return in_organization.where(
            Project.id.in_(
                select(ProjectGrant.project_id).where(ProjectGrant.agent_id == principal.id)
            )
        )
    membership_role = (
        select(Membership.role)
        .where(
            Membership.organization_id == principal.organization_id,
            Membership.user_id == principal.id,
        )
        .scalar_subquery()
    )
    manages = membership_role.in_(
        [role for role in MembershipRole if can_manage_organization(role)]
    )
    granted = and_(
        membership_role.is_not(None),
        Project.id.in_(select(ProjectGrant.project_id).where(ProjectGrant.user_id == principal.id)),
    )
    return in_organization.where(manages | granted)
