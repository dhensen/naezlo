"""Project ACL: the project_grants table, the permission service and the enforced routes."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_in_savepoint, add_member, grant_project_role, sign_in
from todolist.models import (
    Agent,
    MembershipRole,
    PrincipalKind,
    Project,
    ProjectGrant,
    ProjectRole,
    User,
)
from todolist.permissions import effective_project_role, role_at_least, visible_projects
from todolist.principals import Principal

PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}

# Who Grace is in Ada's organization: (membership role, grant on Ada's project or None).
# With it: the effective role, and the expected status of GET, PATCH and DELETE.
MATRIX = [
    pytest.param(MembershipRole.OWNER, None, ProjectRole.ADMIN, (200, 200, 204), id="org-owner"),
    pytest.param(MembershipRole.ADMIN, None, ProjectRole.ADMIN, (200, 200, 204), id="org-admin"),
    pytest.param(
        MembershipRole.ADMIN,
        ProjectRole.VIEWER,
        ProjectRole.ADMIN,
        (200, 200, 204),
        id="org-admin-with-viewer-grant",
    ),
    pytest.param(
        MembershipRole.MEMBER,
        ProjectRole.ADMIN,
        ProjectRole.ADMIN,
        (200, 200, 204),
        id="member-admin-grant",
    ),
    pytest.param(
        MembershipRole.MEMBER,
        ProjectRole.EDITOR,
        ProjectRole.EDITOR,
        (200, 200, 403),
        id="member-editor-grant",
    ),
    pytest.param(
        MembershipRole.MEMBER,
        ProjectRole.VIEWER,
        ProjectRole.VIEWER,
        (200, 403, 403),
        id="member-viewer-grant",
    ),
    pytest.param(MembershipRole.MEMBER, None, None, (404, 404, 404), id="member-no-grant"),
]


async def setup(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    membership_role: MembershipRole,
    grant: ProjectRole | None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Ada creates a project; Grace joins Ada's organization with the given role and grant.

    Returns the project, Grace's /api/me body and the organization's projects URL.
    """
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    url = f"/api/orgs/{org_id}/projects"
    created = await client.post(url, json={"name": "Website"})
    assert created.status_code == 201, created.text
    project = created.json()
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], membership_role)
    if grant is not None:
        await grant_project_role(db_session, project["id"], grace["user"]["id"], grant)
    return project, grace, url


async def load(session: AsyncSession, project: dict[str, Any]) -> Project:
    found = await session.get(Project, uuid.UUID(project["id"]))
    assert found is not None
    return found


async def principal_of(session: AsyncSession, me: dict[str, Any], project: Project) -> Principal:
    user = await session.get(User, uuid.UUID(me["user"]["id"]))
    assert user is not None
    return Principal.for_user(user, project.organization_id)


# --- the routes -----------------------------------------------------------------------------


@pytest.mark.parametrize(("membership_role", "grant", "effective", "statuses"), MATRIX)
async def test_role_matrix(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    membership_role: MembershipRole,
    grant: ProjectRole | None,
    effective: ProjectRole | None,
    statuses: tuple[int, int, int],
) -> None:
    project, grace, url = await setup(client, other_client, db_session, membership_role, grant)
    project_url = f"/api/projects/{project['id']}"
    get_status, patch_status, delete_status = statuses

    stored = await load(db_session, project)
    role = await effective_project_role(
        db_session, await principal_of(db_session, grace, stored), stored
    )
    listed = await other_client.get(url)
    fetched = await other_client.get(project_url)
    patched = await other_client.patch(project_url, json={"name": "Ours"})
    name_after_patch = (await client.get(project_url)).json()["name"]
    deleted = await other_client.delete(project_url)

    assert role == effective
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == ([project["id"]] if effective else [])
    assert fetched.status_code == get_status, fetched.text
    assert patched.status_code == patch_status, patched.text
    assert name_after_patch == ("Ours" if patch_status == 200 else "Website")
    assert deleted.status_code == delete_status, deleted.text
    assert (await client.get(project_url)).status_code == (404 if delete_status == 204 else 200)
    for response in (fetched, patched, deleted):
        if response.status_code == 404:
            assert response.json() == PROJECT_NOT_FOUND
        if response.status_code == 403:
            assert response.json()["code"] == "forbidden"


async def test_creating_a_project_makes_the_creator_its_admin(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _adas, grace, url = await setup(client, other_client, db_session, MembershipRole.MEMBER, None)

    created = await other_client.post(url, json={"name": "Grace's"})
    assert created.status_code == 201, created.text
    project_url = f"/api/projects/{created.json()['id']}"

    grant = (
        await db_session.scalars(
            select(ProjectGrant).where(ProjectGrant.project_id == uuid.UUID(created.json()["id"]))
        )
    ).one()
    assert grant.principal_kind is PrincipalKind.USER
    assert grant.user_id == uuid.UUID(grace["user"]["id"])
    assert grant.agent_id is None
    assert grant.role is ProjectRole.ADMIN
    # A plain member administers their own project and sees only that one.
    assert [p["id"] for p in (await other_client.get(url)).json()] == [created.json()["id"]]
    assert (await other_client.patch(project_url, json={"name": "Mine"})).status_code == 200
    assert (await other_client.delete(project_url)).status_code == 204


async def test_the_owner_sees_projects_of_other_members(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    adas, _grace, url = await setup(client, other_client, db_session, MembershipRole.MEMBER, None)
    graces = (await other_client.post(url, json={"name": "Grace's"})).json()

    listed = await client.get(url)

    assert [p["id"] for p in listed.json()] == [adas["id"], graces["id"]]


async def test_a_grant_is_worth_nothing_without_a_membership(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    url = f"/api/orgs/{ada['organizations'][0]['id']}/projects"
    project = (await client.post(url, json={"name": "Website"})).json()
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await grant_project_role(db_session, project["id"], grace["user"]["id"], ProjectRole.ADMIN)

    response = await other_client.get(f"/api/projects/{project['id']}")

    assert response.status_code == 404
    assert response.json() == PROJECT_NOT_FOUND


# --- the permission service -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "minimum", "expected"),
    [
        (None, ProjectRole.VIEWER, False),
        (ProjectRole.VIEWER, ProjectRole.VIEWER, True),
        (ProjectRole.VIEWER, ProjectRole.EDITOR, False),
        (ProjectRole.EDITOR, ProjectRole.VIEWER, True),
        (ProjectRole.EDITOR, ProjectRole.EDITOR, True),
        (ProjectRole.EDITOR, ProjectRole.ADMIN, False),
        (ProjectRole.ADMIN, ProjectRole.EDITOR, True),
        (ProjectRole.ADMIN, ProjectRole.ADMIN, True),
    ],
)
def test_role_at_least(role: ProjectRole | None, minimum: ProjectRole, expected: bool) -> None:
    assert role_at_least(role, minimum) is expected


async def test_a_principal_of_another_organization_has_no_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    project, grace, _url = await setup(
        client, other_client, db_session, MembershipRole.OWNER, ProjectRole.ADMIN
    )
    stored = await load(db_session, project)
    user = await db_session.get(User, uuid.UUID(grace["user"]["id"]))
    assert user is not None
    # Grace acting in her own default organization, not in the project's.
    elsewhere = Principal.for_user(user, uuid.UUID(grace["organizations"][0]["id"]))

    assert await effective_project_role(db_session, elsewhere, stored) is None


async def test_an_agent_has_the_role_of_its_grant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    url = f"/api/orgs/{org_id}/projects"
    shared = await load(db_session, (await client.post(url, json={"name": "Shared"})).json())
    private = await load(db_session, (await client.post(url, json={"name": "Private"})).json())
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        ProjectGrant(
            project_id=shared.id,
            principal_kind=PrincipalKind.AGENT,
            agent_id=agent.id,
            role=ProjectRole.EDITOR,
        )
    )
    await db_session.flush()
    principal = Principal.for_agent(agent)

    assert await effective_project_role(db_session, principal, shared) is ProjectRole.EDITOR
    assert await effective_project_role(db_session, principal, private) is None
    assert list(await db_session.scalars(visible_projects(principal))) == [shared]


# --- the table ------------------------------------------------------------------------------


async def grant_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(ProjectGrant)) or 0


@pytest.mark.parametrize(
    ("kind", "with_user", "with_agent"),
    [
        (PrincipalKind.USER, False, False),
        (PrincipalKind.USER, False, True),
        (PrincipalKind.USER, True, True),
        (PrincipalKind.AGENT, False, False),
        (PrincipalKind.AGENT, True, False),
        (PrincipalKind.AGENT, True, True),
    ],
)
async def test_the_principal_must_match_its_kind(
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    kind: PrincipalKind,
    with_user: bool,
    with_agent: bool,
) -> None:
    project, grace, _url = await setup(
        client, other_client, db_session, MembershipRole.MEMBER, None
    )
    stored = await load(db_session, project)
    agent = Agent(organization_id=stored.organization_id, name="Claude")
    db_session.add(agent)
    await db_session.flush()
    grant = ProjectGrant(
        project_id=stored.id,
        principal_kind=kind,
        user_id=uuid.UUID(grace["user"]["id"]) if with_user else None,
        agent_id=agent.id if with_agent else None,
        role=ProjectRole.VIEWER,
    )

    with pytest.raises(IntegrityError, match="principal_matches_kind"):
        await add_in_savepoint(db_session, grant)


async def test_one_grant_per_project_and_principal(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    project, grace, _url = await setup(
        client, other_client, db_session, MembershipRole.MEMBER, ProjectRole.VIEWER
    )
    second = ProjectGrant(
        project_id=uuid.UUID(project["id"]),
        principal_kind=PrincipalKind.USER,
        user_id=uuid.UUID(grace["user"]["id"]),
        role=ProjectRole.EDITOR,
    )

    with pytest.raises(IntegrityError, match="uq_project_grants_project_id_user_id"):
        await add_in_savepoint(db_session, second)


async def test_grants_go_with_their_project_and_their_principal(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    project, grace, _url = await setup(
        client, other_client, db_session, MembershipRole.MEMBER, ProjectRole.VIEWER
    )
    assert await grant_count(db_session) == 2  # Ada's admin grant and Grace's

    await db_session.execute(delete(User).where(User.id == uuid.UUID(grace["user"]["id"])))
    assert await grant_count(db_session) == 1

    await db_session.execute(delete(Project).where(Project.id == uuid.UUID(project["id"])))
    assert await grant_count(db_session) == 0
