"""Projects: create, list, change and delete the projects of an organization.

The callers check the acting principal's role on the project (`require_project_role`, see
`todolist.permissions`) or that the user is a member of the organization (`OrgContextDep`).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import PrincipalKind, Project, ProjectGrant, ProjectRole
from todolist.permissions import visible_projects
from todolist.principals import Principal


def _clean_description(description: str | None) -> str | None:
    """Trimmed; an empty description is stored as no description."""
    if description is None:
        return None
    return description.strip() or None


async def list_projects(session: AsyncSession, principal: Principal) -> list[Project]:
    """The projects of the principal's organization that the principal has a role on, oldest
    first."""
    projects = await session.scalars(visible_projects(principal).order_by(Project.id))
    return list(projects)


async def create_project(
    session: AsyncSession,
    organization_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
    description: str | None,
) -> Project:
    project = Project(
        organization_id=organization_id,
        name=name.strip(),
        description=_clean_description(description),
        created_by=created_by,
    )
    session.add(project)
    await session.flush()
    # The creator administers the project, whatever their role in the organization.
    session.add(
        ProjectGrant(
            project_id=project.id,
            principal_kind=PrincipalKind.USER,
            user_id=created_by,
            role=ProjectRole.ADMIN,
        )
    )
    await session.flush()
    return project


async def update_project(
    session: AsyncSession,
    project: Project,
    *,
    name: str | None = None,
    description: str | None = None,
    set_description: bool = False,
) -> Project:
    """Change the name (when given) and the description (when `set_description`; None clears it)."""
    if name is not None:
        project.name = name.strip()
    if set_description:
        project.description = _clean_description(description)
    await session.flush()
    # updated_at is set by the database.
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, project: Project) -> None:
    await session.delete(project)
    await session.flush()
