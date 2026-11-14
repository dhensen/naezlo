"""Projects: create, list, change and delete the projects of an organization.

The callers check that the acting user may see the project (`ProjectContextDep`) or is a member
of the organization (`OrgContextDep`).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Membership, Project


def _clean_description(description: str | None) -> str | None:
    """Trimmed; an empty description is stored as no description."""
    if description is None:
        return None
    return description.strip() or None


async def list_projects(session: AsyncSession, organization_id: uuid.UUID) -> list[Project]:
    """The projects of an organization, oldest first."""
    projects = await session.scalars(
        select(Project).where(Project.organization_id == organization_id).order_by(Project.id)
    )
    return list(projects)


async def get_project_membership(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Project, Membership] | None:
    """The project and the user's membership in its organization; None when the user is not a
    member (or the project does not exist: callers must not tell these apart)."""
    row = (
        await session.execute(
            select(Project, Membership)
            .join(Membership, Membership.organization_id == Project.organization_id)
            .where(Project.id == project_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


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
