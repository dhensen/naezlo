"""Projects: created and listed in an organization, then addressed by their own id.

Every member of the organization can create a project and becomes its admin. After that the
project is visible only to principals with a role on it (see `todolist.permissions`): reading
needs viewer, changing editor, deleting admin.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints, field_validator

from todolist.api.deps import (
    OrgContextDep,
    ProjectAdminContextDep,
    ProjectContextDep,
    ProjectEditorContextDep,
)
from todolist.db import SessionDep
from todolist.models import ListMode, Project, ProjectRole
from todolist.permissions import effective_project_roles
from todolist.services.lists import default_list_mode
from todolist.services.projects import (
    create_project,
    delete_project,
    list_projects,
    update_project,
)

org_router = APIRouter(prefix="/orgs/{org_id}/projects", tags=["projects"])
router = APIRouter(prefix="/projects/{project_id}", tags=["projects"])

# projects.name holds 200 characters.
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ProjectDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ProjectIn(BaseModel):
    name: ProjectName
    description: ProjectDescription | None = None


class ProjectPatch(BaseModel):
    """Only the fields that are sent change. `description: null` removes the description."""

    name: ProjectName | None = None
    description: ProjectDescription | None = None

    @field_validator("name")
    @classmethod
    def _name_is_not_null(cls, value: str | None) -> str | None:
        # Runs only when `name` is sent: leaving it out is fine, null is not a name.
        if value is None:
            raise ValueError("name cannot be null")
        return value


class ProjectOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    # The caller's effective role on the project: what the UI may offer.
    role: ProjectRole
    # The mode a new list gets when none is chosen (it follows the organization's agents):
    # what a "new list" form preselects.
    default_list_mode: ListMode


def _project_out(project: Project, role: ProjectRole, default_mode: ListMode) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        description=project.description,
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        role=role,
        default_list_mode=default_mode,
    )


@org_router.get("")
async def list_projects_route(org: OrgContextDep, session: SessionDep) -> list[ProjectOut]:
    projects = await list_projects(session, org.principal)
    roles = await effective_project_roles(session, org.principal, projects)
    default_mode = await default_list_mode(session, org.organization.id)
    return [
        _project_out(project, roles[project.id], default_mode)
        for project in projects
        if project.id in roles
    ]


@org_router.post("", status_code=201)
async def create_project_route(
    body: ProjectIn, org: OrgContextDep, session: SessionDep
) -> ProjectOut:
    project = await create_project(session, org.principal, body.name, body.description)
    # The creator is the project's admin (their grant, or their role in the organization).
    roles = await effective_project_roles(session, org.principal, [project])
    default_mode = await default_list_mode(session, org.organization.id)
    return _project_out(project, roles[project.id], default_mode)


@router.get("")
async def get_project_route(ctx: ProjectContextDep, session: SessionDep) -> ProjectOut:
    default_mode = await default_list_mode(session, ctx.project.organization_id)
    return _project_out(ctx.project, ctx.role, default_mode)


@router.patch("")
async def update_project_route(
    body: ProjectPatch, ctx: ProjectEditorContextDep, session: SessionDep
) -> ProjectOut:
    project = await update_project(
        session,
        ctx.principal,
        ctx.project,
        name=body.name,
        description=body.description,
        set_description="description" in body.model_fields_set,
    )
    default_mode = await default_list_mode(session, project.organization_id)
    return _project_out(project, ctx.role, default_mode)


@router.delete("", status_code=204)
async def delete_project_route(ctx: ProjectAdminContextDep, session: SessionDep) -> None:
    await delete_project(session, ctx.principal, ctx.project)
