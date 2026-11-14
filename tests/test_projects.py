"""Projects: CRUD as the project's admin, 404 for people outside the organization."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, grant_project_role, sign_in
from todolist.models import MembershipRole, Organization, Project, ProjectRole, User

PROJECT_NOT_FOUND = {"detail": "Project not found", "code": "not_found"}


async def ada_org(client: AsyncClient) -> tuple[str, str]:
    """Sign Ada in; returns her default organization's id and its projects URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    return org_id, f"/api/orgs/{org_id}/projects"


async def create(
    client: AsyncClient, url: str, name: str = "Website", **extra: Any
) -> dict[str, Any]:
    response = await client.post(url, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def join(
    db_session: AsyncSession, other_client: AsyncClient, org_id: str, role: MembershipRole
) -> None:
    """Sign Grace in on `other_client` and make her a member of the organization."""
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], role)


async def project_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Project)) or 0


async def test_create_returns_the_project(client: AsyncClient, db_session: AsyncSession) -> None:
    org_id, url = await ada_org(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await client.post(url, json={"name": "  Website ", "description": " The new site. "})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Website"
    assert body["description"] == "The new site."
    assert body["organization_id"] == org_id
    assert body["created_by"] == ada_id
    assert body["created_at"] is not None
    assert body["updated_at"] is not None
    assert set(body) == {
        "id",
        "organization_id",
        "name",
        "description",
        "created_by",
        "created_at",
        "updated_at",
        "role",
        "default_list_mode",
    }
    assert body["role"] == "admin"
    assert body["default_list_mode"] == "human_only"
    assert await db_session.get(Project, uuid.UUID(body["id"])) is not None


@pytest.mark.parametrize("extra", [{}, {"description": None}, {"description": "   "}])
async def test_create_without_a_description(client: AsyncClient, extra: dict[str, Any]) -> None:
    _, url = await ada_org(client)

    body = await create(client, url, **extra)

    assert body["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 201},
        {"name": "Website", "description": "x" * 2001},
    ],
)
async def test_create_rejects_bad_input(
    client: AsyncClient, db_session: AsyncSession, payload: dict[str, Any]
) -> None:
    _, url = await ada_org(client)

    response = await client.post(url, json=payload)

    assert response.status_code == 422
    assert await project_count(db_session) == 0


async def test_two_projects_can_have_the_same_name(client: AsyncClient) -> None:
    _, url = await ada_org(client)

    first = await create(client, url)
    second = await create(client, url)

    assert first["id"] != second["id"]


async def test_list_returns_the_organizations_projects_oldest_first(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _, url = await ada_org(client)
    first = await create(client, url, "Zebra")
    second = await create(client, url, "Apple", description="Fruit")
    # A project in someone else's organization is not listed.
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await create(other_client, f"/api/orgs/{grace['organizations'][0]['id']}/projects", "Other")

    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == [first, second]


async def test_get_returns_the_project(client: AsyncClient) -> None:
    _, url = await ada_org(client)
    project = await create(client, url, description="The new site")

    response = await client.get(f"/api/projects/{project['id']}")

    assert response.status_code == 200
    assert response.json() == project


async def test_any_member_can_create_a_project(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    await join(db_session, other_client, org_id, MembershipRole.MEMBER)
    grace_id = (await other_client.get("/api/me")).json()["user"]["id"]

    created = await create(other_client, url, "Grace's")

    assert created["created_by"] == grace_id
    # The access rules after creation are in tests/test_project_permissions.py.
    assert (await other_client.get(url)).json() == [created]


async def test_update_changes_only_what_is_sent(client: AsyncClient) -> None:
    _, url = await ada_org(client)
    project = await create(client, url, description="The new site")
    project_url = f"/api/projects/{project['id']}"

    renamed = await client.patch(project_url, json={"name": " Website 2 "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {
        **project,
        "name": "Website 2",
        "updated_at": renamed.json()["updated_at"],
    }

    described = await client.patch(project_url, json={"description": "Relaunch"})
    assert described.json()["name"] == "Website 2"
    assert described.json()["description"] == "Relaunch"

    unchanged = await client.patch(project_url, json={})
    assert unchanged.status_code == 200
    assert unchanged.json()["description"] == "Relaunch"

    cleared = await client.patch(project_url, json={"description": None})
    assert cleared.json()["description"] is None
    assert cleared.json()["name"] == "Website 2"
    assert (await client.get(project_url)).json() == cleared.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"name": " "},
        {"name": "x" * 201},
        {"description": "x" * 2001},
    ],
)
async def test_update_rejects_bad_input(client: AsyncClient, payload: dict[str, Any]) -> None:
    _, url = await ada_org(client)
    project = await create(client, url)

    response = await client.patch(f"/api/projects/{project['id']}", json=payload)

    assert response.status_code == 422
    assert (await client.get(url)).json() == [project]


async def test_delete_removes_the_project(client: AsyncClient, db_session: AsyncSession) -> None:
    _, url = await ada_org(client)
    project = await create(client, url)
    other = await create(client, url, "Other")

    response = await client.delete(f"/api/projects/{project['id']}")

    assert response.status_code == 204
    assert (await client.get(url)).json() == [other]
    assert await project_count(db_session) == 1
    assert (await client.get(f"/api/projects/{project['id']}")).status_code == 404


async def test_non_members_get_404_on_every_route(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _, url = await ada_org(client)
    project = await create(client, url)
    project_url = f"/api/projects/{project['id']}"
    await sign_in(other_client, "grace@example.com", "Grace")

    org_responses = [
        await other_client.get(url),
        await other_client.post(url, json={"name": "Mine"}),
    ]
    project_responses = [
        await other_client.get(project_url),
        await other_client.patch(project_url, json={"name": "Mine"}),
        await other_client.delete(project_url),
    ]

    for response in org_responses:
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "Organization not found", "code": "not_found"}
    for response in project_responses:
        assert response.status_code == 404, response.text
        assert response.json() == PROJECT_NOT_FOUND
    assert (await client.get(url)).json() == [project]


async def test_a_removed_member_gets_404(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    project = await create(client, url)
    await join(db_session, other_client, org_id, MembershipRole.MEMBER)
    grace_id = (await other_client.get("/api/me")).json()["user"]["id"]
    await grant_project_role(db_session, project["id"], grace_id, ProjectRole.ADMIN)
    assert (await other_client.get(f"/api/projects/{project['id']}")).status_code == 200

    removed = await client.delete(f"/api/orgs/{org_id}/members/{grace_id}")
    response = await other_client.get(f"/api/projects/{project['id']}")

    assert removed.status_code == 204
    assert response.status_code == 404
    assert response.json() == PROJECT_NOT_FOUND
    # Joining again does not bring the old access back.
    await add_member(db_session, org_id, grace_id, MembershipRole.MEMBER)
    assert (await other_client.get(f"/api/projects/{project['id']}")).status_code == 404


async def test_unknown_project_is_404(client: AsyncClient) -> None:
    await sign_in(client)
    project_url = f"/api/projects/{uuid.uuid7()}"

    responses = [
        await client.get(project_url),
        await client.patch(project_url, json={"name": "Mine"}),
        await client.delete(project_url),
    ]

    for response in responses:
        assert response.status_code == 404
        assert response.json() == PROJECT_NOT_FOUND


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/orgs/{id}/projects"),
        ("POST", "/api/orgs/{id}/projects"),
        ("GET", "/api/projects/{id}"),
        ("PATCH", "/api/projects/{id}"),
        ("DELETE", "/api/projects/{id}"),
    ],
)
async def test_endpoints_need_a_signed_in_user(client: AsyncClient, method: str, path: str) -> None:
    response = await client.request(method, path.format(id=uuid.uuid7()), json={"name": "Website"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


async def test_deleting_the_organization_deletes_its_projects(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    await create(client, url)

    await db_session.execute(delete(Organization).where(Organization.id == uuid.UUID(org_id)))

    assert await project_count(db_session) == 0


async def test_deleting_the_creator_keeps_the_project(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, url = await ada_org(client)
    project = await create(client, url)

    await db_session.execute(delete(User).where(User.id == uuid.UUID(project["created_by"])))

    created_by = await db_session.scalar(
        select(Project.created_by).where(Project.id == uuid.UUID(project["id"]))
    )
    assert await project_count(db_session) == 1
    assert created_by is None


async def test_every_answer_has_the_callers_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    website = await create(client, url)
    shop = await create(client, url, "Shop")
    hidden = await create(client, url, "Hidden")
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    grace_id = grace["user"]["id"]
    await add_member(db_session, org_id, grace_id, MembershipRole.MEMBER)
    await grant_project_role(db_session, website["id"], grace_id, ProjectRole.VIEWER)
    await grant_project_role(db_session, shop["id"], grace_id, ProjectRole.EDITOR)

    # The owner is admin everywhere, a member has the role of their grant.
    assert [p["role"] for p in (await client.get(url)).json()] == ["admin"] * 3
    listed = (await other_client.get(url)).json()
    assert [(p["name"], p["role"]) for p in listed] == [("Website", "viewer"), ("Shop", "editor")]
    assert hidden["id"] not in [p["id"] for p in listed]

    one = await other_client.get(f"/api/projects/{website['id']}")
    assert one.json()["role"] == "viewer"
    renamed = await other_client.patch(f"/api/projects/{shop['id']}", json={"name": "Store"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["role"] == "editor"

    # A project a member creates is theirs to administer.
    assert (await create(other_client, url, "Mine"))["role"] == "admin"


async def test_default_list_mode_follows_the_agents_of_the_organization(
    client: AsyncClient,
) -> None:
    org_id, url = await ada_org(client)
    project_url = f"/api/projects/{(await create(client, url))['id']}"
    assert (await client.get(project_url)).json()["default_list_mode"] == "human_only"

    agent = await client.post(f"/api/orgs/{org_id}/agents", json={"name": "Claude"})
    assert agent.status_code == 201, agent.text

    assert (await client.get(project_url)).json()["default_list_mode"] == "mixed"
    assert [project["default_list_mode"] for project in (await client.get(url)).json()] == ["mixed"]
    renamed = await client.patch(project_url, json={"name": "Site"})
    assert renamed.json()["default_list_mode"] == "mixed"
    assert (await create(client, url, "Second"))["default_list_mode"] == "mixed"
