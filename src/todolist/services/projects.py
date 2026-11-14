"""Projects: create, list, change and delete the projects of an organization.

The callers check the acting principal's role on the project (`require_project_role`, see
`todolist.permissions`) or that the user is a member of the organization (`OrgContextDep`).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import AuditAction, Project, ProjectGrant, ProjectRole
from todolist.permissions import visible_projects
from todolist.principals import Principal
from todolist.services.audit import changes, record_event


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
    principal: Principal,
    name: str,
    description: str | None,
) -> Project:
    """Add a project to the organization the principal acts in; the principal becomes its
    admin."""
    project = Project(
        organization_id=principal.organization_id,
        name=name.strip(),
        description=_clean_description(description),
        # created_by refers to a user; a project made by an agent has none.
        created_by=principal.id if principal.is_user else None,
    )
    session.add(project)
    await session.flush()
    # The creator administers the project, whatever their role in the organization.
    session.add(
        ProjectGrant(
            project_id=project.id,
            principal_kind=principal.kind,
            user_id=principal.id if principal.is_user else None,
            agent_id=principal.id if principal.is_agent else None,
            role=ProjectRole.ADMIN,
        )
    )
    await session.flush()
    await record_event(
        session,
        principal,
        AuditAction.PROJECT_CREATED,
        target_kind="project",
        target_id=project.id,
        project_id=project.id,
        details={"name": project.name},
    )
    return project


async def update_project(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    name: str | None = None,
    description: str | None = None,
    set_description: bool = False,
) -> Project:
    """Change the name (when given) and the description (when `set_description`; None clears it)."""
    old = {"name": project.name, "description": project.description}
    if name is not None:
        project.name = name.strip()
    if set_description:
        project.description = _clean_description(description)
    await session.flush()
    # updated_at is set by the database.
    await session.refresh(project)
    changed = changes(old, {"name": project.name, "description": project.description})
    if changed:
        await record_event(
            session,
            principal,
            AuditAction.PROJECT_UPDATED,
            target_kind="project",
            target_id=project.id,
            project_id=project.id,
            details={"name": project.name, "changes": changed},
        )
    return project


async def delete_project(session: AsyncSession, principal: Principal, project: Project) -> None:
    """Delete the project with its lists and items. One event is recorded, for the project."""
    project_id, name = project.id, project.name
    await session.delete(project)
    await session.flush()
    await record_event(
        session,
        principal,
        AuditAction.PROJECT_DELETED,
        target_kind="project",
        target_id=project_id,
        project_id=project_id,
        details={"name": name},
    )
