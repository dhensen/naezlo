"""Agents: CRUD, name uniqueness per organization, permissions, and the Principal type."""

import dataclasses
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import Agent, MembershipRole, Organization, User
from naezlo.principals import Principal, PrincipalKind
from tests.helpers import add_in_savepoint, add_member, sign_in


async def ada_org(client: AsyncClient) -> tuple[str, str]:
    """Sign Ada in; returns her default organization's id and its agents URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    return org_id, f"/api/orgs/{org_id}/agents"


async def create(
    client: AsyncClient, url: str, name: str = "Claude", **extra: Any
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


async def agent_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Agent)) or 0


async def test_create_returns_the_agent(client: AsyncClient, db_session: AsyncSession) -> None:
    org_id, url = await ada_org(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await client.post(
        url, json={"name": "  Claude ", "description": " Reviews the backlog. "}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Claude"
    assert body["description"] == "Reviews the backlog."
    assert body["created_by"] == ada_id
    assert body["created_at"] is not None
    assert body["updated_at"] is not None
    assert body["project_count"] == 0
    assert body["list_count"] == 0
    assert set(body) == {
        "id",
        "name",
        "description",
        "created_by",
        "project_count",
        "list_count",
        "created_at",
        "updated_at",
    }

    agent = await db_session.get(Agent, uuid.UUID(body["id"]))
    assert agent is not None
    assert str(agent.organization_id) == org_id


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
        {"name": "Claude", "description": "x" * 2001},
    ],
)
async def test_create_rejects_bad_input(
    client: AsyncClient, db_session: AsyncSession, payload: dict[str, Any]
) -> None:
    _, url = await ada_org(client)

    response = await client.post(url, json=payload)

    assert response.status_code == 422
    assert await agent_count(db_session) == 0


async def test_list_returns_the_organizations_agents_oldest_first(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _, url = await ada_org(client)
    first = await create(client, url, "Zed")
    second = await create(client, url, "Codex", description="Writes code")
    # An agent in someone else's organization is not listed.
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await create(other_client, f"/api/orgs/{grace['organizations'][0]['id']}/agents", "Other")

    response = await client.get(url)

    assert response.status_code == 200
    assert response.json() == [first, second]


@pytest.mark.parametrize("role", [MembershipRole.MEMBER, MembershipRole.ADMIN])
async def test_any_member_can_list(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, role: MembershipRole
) -> None:
    org_id, url = await ada_org(client)
    agent = await create(client, url)
    await join(db_session, other_client, org_id, role)

    response = await other_client.get(url)

    assert response.status_code == 200
    assert response.json() == [agent]


async def test_admin_can_create_update_and_delete(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    await join(db_session, other_client, org_id, MembershipRole.ADMIN)

    agent = await create(other_client, url)
    patched = await other_client.patch(f"{url}/{agent['id']}", json={"name": "Claude 2"})
    deleted = await other_client.delete(f"{url}/{agent['id']}")

    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Claude 2"
    assert deleted.status_code == 204
    assert await agent_count(db_session) == 0


async def test_member_cannot_create_update_or_delete(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    agent = await create(client, url)
    await join(db_session, other_client, org_id, MembershipRole.MEMBER)

    responses = [
        await other_client.post(url, json={"name": "Codex"}),
        await other_client.patch(f"{url}/{agent['id']}", json={"name": "Renamed"}),
        await other_client.delete(f"{url}/{agent['id']}"),
        # Also for an agent that does not exist: the role is checked first.
        await other_client.patch(f"{url}/{uuid.uuid7()}", json={"name": "Renamed"}),
        await other_client.delete(f"{url}/{uuid.uuid7()}"),
    ]

    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"
    assert (await client.get(url)).json() == [agent]


async def test_non_members_get_404(client: AsyncClient, other_client: AsyncClient) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url)
    await sign_in(other_client, "grace@example.com", "Grace")

    responses = [
        await other_client.get(url),
        await other_client.post(url, json={"name": "Codex"}),
        await other_client.patch(f"{url}/{agent['id']}", json={"name": "Renamed"}),
        await other_client.delete(f"{url}/{agent['id']}"),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "Organization not found", "code": "not_found"}
    assert (await client.get(url)).json() == [agent]


@pytest.mark.parametrize(
    ("method", "suffix"), [("GET", ""), ("POST", ""), ("PATCH", "/{id}"), ("DELETE", "/{id}")]
)
async def test_endpoints_need_a_signed_in_user(
    client: AsyncClient, method: str, suffix: str
) -> None:
    path = f"/api/orgs/{uuid.uuid7()}/agents" + suffix.format(id=uuid.uuid7())

    response = await client.request(method, path, json={"name": "Claude"})

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


async def test_names_are_unique_per_organization(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url)

    response = await client.post(url, json={"name": " Claude "})

    assert response.status_code == 409
    assert response.json() == {
        "detail": 'This organization already has an agent "Claude"',
        "code": "agent_name_taken",
    }
    assert (await client.get(url)).json() == [agent]

    # Another organization can use the same name, and so can this one in another case.
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await create(other_client, f"/api/orgs/{grace['organizations'][0]['id']}/agents", "Claude")
    await create(client, url, "claude")
    assert await agent_count(db_session) == 3


async def test_rename_to_a_taken_name_is_409(client: AsyncClient) -> None:
    _, url = await ada_org(client)
    claude = await create(client, url, "Claude")
    codex = await create(client, url, "Codex")

    response = await client.patch(
        f"{url}/{codex['id']}", json={"name": "Claude", "description": "Changed"}
    )

    assert response.status_code == 409
    assert response.json()["code"] == "agent_name_taken"
    # Nothing of the failed request is kept, and the session still works.
    assert (await client.get(url)).json() == [claude, codex]
    # Keeping its own name is not a conflict.
    same = await client.patch(f"{url}/{codex['id']}", json={"name": "Codex"})
    assert same.status_code == 200, same.text


async def test_update_changes_only_what_is_sent(client: AsyncClient) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url, description="Reviews the backlog")
    agent_url = f"{url}/{agent['id']}"

    renamed = await client.patch(agent_url, json={"name": " Claude Code "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {
        **agent,
        "name": "Claude Code",
        "updated_at": renamed.json()["updated_at"],
    }

    described = await client.patch(agent_url, json={"description": "Plans sprints"})
    assert described.json()["name"] == "Claude Code"
    assert described.json()["description"] == "Plans sprints"

    unchanged = await client.patch(agent_url, json={})
    assert unchanged.status_code == 200
    assert unchanged.json()["description"] == "Plans sprints"

    cleared = await client.patch(agent_url, json={"description": None})
    assert cleared.json()["description"] is None
    assert cleared.json()["name"] == "Claude Code"
    assert (await client.get(url)).json() == [cleared.json()]


@pytest.mark.parametrize(
    "payload", [{"name": None}, {"name": " "}, {"name": "x" * 201}, {"description": "x" * 2001}]
)
async def test_update_rejects_bad_input(client: AsyncClient, payload: dict[str, Any]) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url)

    response = await client.patch(f"{url}/{agent['id']}", json=payload)

    assert response.status_code == 422
    assert (await client.get(url)).json() == [agent]


async def test_delete_removes_the_agent(client: AsyncClient, db_session: AsyncSession) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url)
    other = await create(client, url, "Codex")

    response = await client.delete(f"{url}/{agent['id']}")

    assert response.status_code == 204
    assert (await client.get(url)).json() == [other]
    assert await agent_count(db_session) == 1
    # The name is free again.
    await create(client, url, "Claude")


async def test_unknown_and_foreign_agents_are_404(
    client: AsyncClient, other_client: AsyncClient
) -> None:
    _, url = await ada_org(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    foreign_url = f"/api/orgs/{grace['organizations'][0]['id']}/agents"
    foreign = await create(other_client, foreign_url, "Theirs")

    for agent_id in (str(uuid.uuid7()), foreign["id"]):
        patched = await client.patch(f"{url}/{agent_id}", json={"name": "Mine"})
        deleted = await client.delete(f"{url}/{agent_id}")
        assert patched.status_code == 404
        assert patched.json() == {"detail": "Agent not found", "code": "not_found"}
        assert deleted.status_code == 404

    assert (await other_client.get(foreign_url)).json() == [foreign]


async def test_database_enforces_the_unique_name(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    await create(client, url)

    with pytest.raises(IntegrityError, match="uq_agents_organization_id_name"):
        await add_in_savepoint(db_session, Agent(organization_id=uuid.UUID(org_id), name="Claude"))


async def test_deleting_the_organization_deletes_its_agents(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    await create(client, url)

    await db_session.execute(delete(Organization).where(Organization.id == uuid.UUID(org_id)))

    assert await agent_count(db_session) == 0


async def test_deleting_the_creator_keeps_the_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, url = await ada_org(client)
    agent = await create(client, url)

    await db_session.execute(delete(User).where(User.id == uuid.UUID(agent["created_by"])))

    created_by = await db_session.scalar(
        select(Agent.created_by).where(Agent.id == uuid.UUID(agent["id"]))
    )
    assert await agent_count(db_session) == 1
    assert created_by is None


async def test_principal_for_a_user_and_an_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, url = await ada_org(client)
    created = await create(client, url)
    agent = await db_session.get(Agent, uuid.UUID(created["id"]))
    user = await db_session.scalar(select(User).where(User.email == "ada@example.com"))
    assert agent is not None
    assert user is not None

    as_user = Principal.for_user(user, uuid.UUID(org_id))
    as_agent = Principal.for_agent(agent)

    assert as_user == Principal(PrincipalKind.USER, user.id, uuid.UUID(org_id), "Ada")
    assert as_user.is_user
    assert not as_user.is_agent
    assert as_agent == Principal(PrincipalKind.AGENT, agent.id, uuid.UUID(org_id), "Claude")
    assert as_agent.is_agent
    assert not as_agent.is_user
    assert [kind.value for kind in PrincipalKind] == ["user", "agent"]
    # A value type: immutable, and equal by value (usable as a dict key).
    with pytest.raises(dataclasses.FrozenInstanceError):
        as_user.name = "Someone else"  # pyright: ignore[reportAttributeAccessIssue]
    assert as_agent in {Principal.for_agent(agent)}


async def test_list_counts_the_projects_and_lists_an_agent_can_access(
    client: AsyncClient,
) -> None:
    org_id, url = await ada_org(client)
    claude = await create(client, url, "Claude")
    codex = await create(client, url, "Codex")

    async def post(path: str, **body: Any) -> str:
        response = await client.post(path, json=body)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    async def grant(path: str, role: str) -> None:
        response = await client.put(
            path, json={"principal_kind": "agent", "principal_id": claude["id"], "role": role}
        )
        assert response.status_code in (200, 201), response.text

    # Claude has a role on the first project: its mixed and AI-only lists count, the
    # human-only one and the one closed with a `none` grant do not.
    first = await post(f"/api/orgs/{org_id}/projects", name="First")
    await post(f"/api/projects/{first}/lists", name="Mixed", mode="mixed")
    await post(f"/api/projects/{first}/lists", name="AI", mode="ai_only")
    await post(f"/api/projects/{first}/lists", name="Human", mode="human_only")
    closed = await post(f"/api/projects/{first}/lists", name="Closed", mode="mixed")
    await grant(f"/api/projects/{first}/grants", "editor")
    await grant(f"/api/lists/{closed}/grants", "none")
    # A list grant alone makes the second project count; the third has nothing for Claude.
    second = await post(f"/api/orgs/{org_id}/projects", name="Second")
    shared = await post(f"/api/projects/{second}/lists", name="Shared", mode="mixed")
    await post(f"/api/projects/{second}/lists", name="Not shared", mode="mixed")
    await grant(f"/api/lists/{shared}/grants", "viewer")
    third = await post(f"/api/orgs/{org_id}/projects", name="Third")
    await post(f"/api/projects/{third}/lists", name="Other", mode="mixed")

    agents = {agent["name"]: agent for agent in (await client.get(url)).json()}

    assert (agents["Claude"]["project_count"], agents["Claude"]["list_count"]) == (2, 3)
    assert (agents["Codex"]["project_count"], agents["Codex"]["list_count"]) == (0, 0)

    renamed = await client.patch(f"{url}/{claude['id']}", json={"name": "Claude 2"})
    assert (renamed.json()["project_count"], renamed.json()["list_count"]) == (2, 3)
    assert codex["list_count"] == 0
