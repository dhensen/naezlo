"""Dependencies shared by the routers.

Org-scoped routes (`/orgs/{org_id}/...`) take `org: OrgContextDep`, or `org: OrgAdminContextDep`
when the action needs an owner or admin. Project-scoped routes (`/projects/{project_id}...`) take
`ctx: ProjectContextDep` (viewer or higher), `ProjectEditorContextDep` or `ProjectAdminContextDep`,
all built with `require_project_role(...)` on the permission service (`todolist.permissions`).
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from todolist.auth import CurrentUser
from todolist.db import SessionDep
from todolist.errors import ForbiddenError, NotFoundError
from todolist.models import Membership, MembershipRole, Organization, Project, ProjectRole, User
from todolist.permissions import effective_project_role, role_at_least
from todolist.principals import Principal
from todolist.services.organizations import can_manage_organization, get_organization_membership


@dataclass(frozen=True)
class OrgContext:
    """The organization in the path and the caller's membership in it."""

    organization: Organization
    membership: Membership
    user: User

    @property
    def role(self) -> MembershipRole:
        return self.membership.role

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.organization.id)


async def org_context(org_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OrgContext:
    """Resolve `{org_id}` for the signed-in user; 404 when they are not a member."""
    found = await get_organization_membership(session, org_id, user.id)
    if found is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Organization not found")
    organization, membership = found
    return OrgContext(organization=organization, membership=membership, user=user)


OrgContextDep = Annotated[OrgContext, Depends(org_context)]


async def org_admin_context(org: OrgContextDep) -> OrgContext:
    """Like `org_context`, and 403 unless the caller is owner or admin of the organization."""
    if not can_manage_organization(org.role):
        raise ForbiddenError("Only organization owners and admins can do this")
    return org


OrgAdminContextDep = Annotated[OrgContext, Depends(org_admin_context)]


@dataclass(frozen=True)
class ProjectContext:
    """The project in the path and the caller's effective role on it."""

    project: Project
    role: ProjectRole
    user: User

    @property
    def principal(self) -> Principal:
        """The caller as the actor for permission checks and audit events."""
        return Principal.for_user(self.user, self.project.organization_id)


async def project_context(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ProjectContext:
    """Resolve `{project_id}` for the signed-in user; 404 when they have no role on the project."""
    project = await session.get(Project, project_id)
    role = (
        None
        if project is None
        # effective_project_role checks the membership itself, so this principal claims nothing.
        else await effective_project_role(
            session, Principal.for_user(user, project.organization_id), project
        )
    )
    if project is None or role is None:
        # Same answer for "does not exist" and "not yours": don't reveal which ids exist.
        raise NotFoundError("Project not found")
    return ProjectContext(project=project, role=role, user=user)


def require_project_role(minimum: ProjectRole) -> Callable[..., Awaitable[ProjectContext]]:
    """A dependency that resolves `{project_id}` and needs at least the role `minimum` on it.

    404 when the caller has no role on the project, 403 when their role is too low. Use the
    aliases below in route signatures.
    """

    async def dependency(
        ctx: Annotated[ProjectContext, Depends(project_context)],
    ) -> ProjectContext:
        if not role_at_least(ctx.role, minimum):
            raise ForbiddenError(f"This needs the {minimum.value} role on the project")
        return ctx

    return dependency


# Any role on the project (viewer or higher).
ProjectContextDep = Annotated[ProjectContext, Depends(require_project_role(ProjectRole.VIEWER))]
ProjectEditorContextDep = Annotated[
    ProjectContext, Depends(require_project_role(ProjectRole.EDITOR))
]
ProjectAdminContextDep = Annotated[ProjectContext, Depends(require_project_role(ProjectRole.ADMIN))]
