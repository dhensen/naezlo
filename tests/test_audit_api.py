"""Audit log API: the events of a project or a list, newest first, for its admins."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_member, grant_list_role, sign_in
from tests.test_items import ada_list, create, join
from todolist.models import (
    Agent,
    AuditAction,
    ListRole,
    MembershipRole,
    ProjectRole,
    TodoList,
)
from todolist.principals import Principal
from todolist.services.audit import action_group
from todolist.services.items import create_item


async def page(client: AsyncClient, url: str, **params: Any) -> dict[str, Any]:
    response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def actions(client: AsyncClient, url: str, **params: Any) -> list[str]:
    return [event["action"] for event in (await page(client, url, **params))["events"]]


async def second_list(client: AsyncClient, project_id: str, name: str = "Later") -> str:
    response = await client.post(
        f"/api/projects/{project_id}/lists", json={"name": name, "mode": "mixed"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def agent_item(db_session: AsyncSession, org_id: str, list_id: str, title: str) -> Agent:
    """Let a new agent, Claude, add an item to the list (through the service, as MCP will)."""
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    todo_list = await db_session.get(TodoList, uuid.UUID(list_id))
    assert todo_list is not None
    await create_item(db_session, Principal.for_agent(agent), todo_list, title, None)
    return agent


async def test_project_log_has_the_project_its_lists_and_items_newest_first(
    client: AsyncClient,
) -> None:
    ada = await sign_in(client)
    _, project_id, list_id, items_url = await ada_list(client)
    item = await create(client, items_url, "Buy domain")
    response = await client.patch(f"/api/items/{item['id']}", json={"status": "done"})
    assert response.status_code == 200, response.text
    response = await client.patch(f"/api/projects/{project_id}", json={"name": "Site"})
    assert response.status_code == 200, response.text

    body = await page(client, f"/api/projects/{project_id}/audit")
    assert body["next_cursor"] is None
    assert [event["action"] for event in body["events"]] == [
        "project.updated",
        "item.completed",
        "item.created",
        "list.created",
        "project.created",
    ]
    completed = body["events"][1]
    assert completed == {
        "id": completed["id"],
        "created_at": completed["created_at"],
        "actor": {"kind": "user", "id": ada["user"]["id"], "name": "Ada"},
        "action": "item.completed",
        "target_kind": "item",
        "target_id": item["id"],
        "project_id": project_id,
        "list_id": list_id,
        "details": completed["details"],
    }
    assert completed["details"]["title"] == "Buy domain"
    assert completed["created_at"] is not None
    updated = body["events"][0]
    assert updated["list_id"] is None
    assert updated["details"]["changes"] == {"name": {"old": "Website", "new": "Site"}}


async def test_list_log_has_only_that_list_and_its_items(client: AsyncClient) -> None:
    _, project_id, list_id, items_url = await ada_list(client)
    other_list_id = await second_list(client, project_id)
    await create(client, items_url, "Buy domain")
    await create(client, f"/api/lists/{other_list_id}/items", "Something else")
    response = await client.patch(f"/api/lists/{list_id}", json={"name": "Launch day"})
    assert response.status_code == 200, response.text

    body = await page(client, f"/api/lists/{list_id}/audit")
    assert [event["action"] for event in body["events"]] == [
        "list.updated",
        "item.created",
        "list.created",
    ]
    assert {event["list_id"] for event in body["events"]} == {list_id}
    assert body["events"][1]["details"]["title"] == "Buy domain"

    other = await page(client, f"/api/lists/{other_list_id}/audit")
    assert [event["action"] for event in other["events"]] == ["item.created", "list.created"]
    assert other["events"][0]["details"]["title"] == "Something else"


async def test_project_log_leaves_out_other_projects(client: AsyncClient) -> None:
    org_id, project_id, _, _ = await ada_list(client)
    response = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Other"})
    assert response.status_code == 201, response.text
    other_id = response.json()["id"]
    await second_list(client, other_id)

    assert await actions(client, f"/api/projects/{project_id}/audit") == [
        "list.created",
        "project.created",
    ]
    assert await actions(client, f"/api/projects/{other_id}/audit") == [
        "list.created",
        "project.created",
    ]


async def test_project_log_keeps_the_events_of_a_deleted_list(client: AsyncClient) -> None:
    _, project_id, list_id, items_url = await ada_list(client)
    await create(client, items_url)
    response = await client.delete(f"/api/lists/{list_id}")
    assert response.status_code == 204, response.text

    assert await actions(client, f"/api/projects/{project_id}/audit") == [
        "list.deleted",
        "item.created",
        "list.created",
        "project.created",
    ]


async def test_pagination(client: AsyncClient) -> None:
    _, project_id, list_id, items_url = await ada_list(client)
    for number in range(5):
        await create(client, items_url, f"Item {number}")
    url = f"/api/lists/{list_id}/audit"

    first = await page(client, url, limit=2)
    assert [event["details"]["title"] for event in first["events"]] == ["Item 4", "Item 3"]
    assert first["next_cursor"] is not None
    second = await page(client, url, limit=2, cursor=first["next_cursor"])
    assert [event["details"]["title"] for event in second["events"]] == ["Item 2", "Item 1"]
    third = await page(client, url, limit=2, cursor=second["next_cursor"])
    assert [event["action"] for event in third["events"]] == ["item.created", "list.created"]
    assert third["next_cursor"] is None

    # A page that ends exactly at the last event has no next page.
    exact = await page(client, url, limit=6)
    assert len(exact["events"]) == 6
    assert exact["next_cursor"] is None

    # The project log pages the same way, and new events do not shift an old cursor.
    project_url = f"/api/projects/{project_id}/audit"
    first = await page(client, project_url, limit=3)
    await create(client, items_url, "Late")
    rest = await page(client, project_url, limit=200, cursor=first["next_cursor"])
    seen = [event["id"] for event in first["events"] + rest["events"]]
    assert len(seen) == len(set(seen)) == 7
    assert rest["next_cursor"] is None


async def test_default_limit_is_50_and_the_maximum_200(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, _, list_id, _ = await ada_list(client)
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    todo_list = await db_session.get(TodoList, uuid.UUID(list_id))
    assert todo_list is not None
    for number in range(55):
        await create_item(db_session, Principal.for_agent(agent), todo_list, f"Item {number}", None)
    url = f"/api/lists/{list_id}/audit"

    body = await page(client, url)
    assert len(body["events"]) == 50
    assert body["next_cursor"] is not None
    rest = await page(client, url, cursor=body["next_cursor"])
    assert len(rest["events"]) == 6
    assert rest["next_cursor"] is None
    assert len((await page(client, url, limit=200))["events"]) == 56

    for limit in (0, 201, "many"):
        response = await client.get(url, params={"limit": limit})
        assert response.status_code == 422, response.text


@pytest.mark.parametrize("cursor", ["nonsense", "bm9uc2Vuc2U=", "MjAyNi0xMS0xNHxub3Bl"])
async def test_a_bad_cursor_is_a_422(client: AsyncClient, cursor: str) -> None:
    _, project_id, list_id, _ = await ada_list(client)
    for url in (f"/api/projects/{project_id}/audit", f"/api/lists/{list_id}/audit"):
        response = await client.get(url, params={"cursor": cursor})
        assert response.status_code == 422, response.text
        assert response.json() == {"detail": "Invalid cursor", "code": "invalid_cursor"}


async def test_filters(client: AsyncClient, db_session: AsyncSession) -> None:
    ada = await sign_in(client)
    org_id, project_id, list_id, items_url = await ada_list(client)
    response = await client.patch(f"/api/lists/{list_id}", json={"mode": "mixed"})
    assert response.status_code == 200, response.text
    item = await create(client, items_url, "Buy domain")
    response = await client.patch(f"/api/items/{item['id']}", json={"status": "done"})
    assert response.status_code == 200, response.text
    agent = await agent_item(db_session, org_id, list_id, "Write tests")

    for url in (f"/api/projects/{project_id}/audit", f"/api/lists/{list_id}/audit"):
        assert await actions(client, url, action="item.") == [
            "item.created",
            "item.completed",
            "item.created",
        ]
        assert await actions(client, url, action="item.completed") == ["item.completed"]
        assert await actions(client, url, action="list.") == ["list.updated", "list.created"]
        assert await actions(client, url, action="nothing.") == []
        # The prefix is taken literally: no wildcards.
        assert await actions(client, url, action="%") == []
        assert await actions(client, url, action="item_") == []

        by_agents = await page(client, url, actor_kind="agent")
        assert [event["details"]["title"] for event in by_agents["events"]] == ["Write tests"]
        assert by_agents["events"][0]["actor"] == {
            "kind": "agent",
            "id": str(agent.id),
            "name": "Claude",
        }
        by_users = await page(client, url, actor_kind="user")
        assert {event["actor"]["name"] for event in by_users["events"]} == {"Ada"}
        assert "Write tests" not in [e["details"].get("title") for e in by_users["events"]]

        assert await actions(client, url, actor_id=str(agent.id)) == ["item.created"]
        assert await actions(client, url, actor_id=ada["user"]["id"], action="item.") == [
            "item.completed",
            "item.created",
        ]
        assert await actions(client, url, actor_id=str(uuid.uuid4())) == []
        assert await actions(client, url, actor_kind="agent", actor_id=ada["user"]["id"]) == []

        # Filters and paging together.
        first = await page(client, url, action="item.", limit=2)
        assert len(first["events"]) == 2
        rest = await page(client, url, action="item.", limit=2, cursor=first["next_cursor"])
        assert [event["action"] for event in rest["events"]] == ["item.created"]
        assert rest["next_cursor"] is None

        for params in ({"actor_kind": "robot"}, {"actor_id": "me"}):
            response = await client.get(url, params=params)
            assert response.status_code == 422, response.text


@pytest.mark.parametrize("role", [ProjectRole.VIEWER, ProjectRole.EDITOR])
async def test_project_log_is_for_project_admins(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession, role: ProjectRole
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    await join(db_session, other_client, org_id, project_id, role)

    for url in (f"/api/projects/{project_id}/audit", f"/api/lists/{list_id}/audit"):
        response = await other_client.get(url)
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"


async def test_a_project_admin_reads_both_logs(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    await join(db_session, other_client, org_id, project_id, ProjectRole.ADMIN)

    assert await actions(other_client, f"/api/projects/{project_id}/audit") == [
        "list.created",
        "project.created",
    ]
    assert await actions(other_client, f"/api/lists/{list_id}/audit") == ["list.created"]


async def test_list_log_follows_the_list_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    grace_id = await join(db_session, other_client, org_id, project_id, None)
    url = f"/api/lists/{list_id}/audit"

    await grant_list_role(db_session, list_id, grace_id, ListRole.EDITOR)
    response = await other_client.get(url)
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "forbidden"

    response = await client.put(
        f"/api/lists/{list_id}/grants",
        json={"principal_kind": "user", "principal_id": grace_id, "role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert await actions(other_client, url) == ["list_grant.set", "list.created"]
    # Admin of a list only: the project's log does not exist for her.
    response = await other_client.get(f"/api/projects/{project_id}/audit")
    assert response.status_code == 404, response.text


async def test_project_admin_does_not_see_a_list_that_is_hidden_from_them(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, items_url = await ada_list(client)
    open_list_id = await second_list(client, project_id)
    await create(client, items_url, "Secret")
    await create(client, f"/api/lists/{open_list_id}/items", "Open")
    grace_id = await join(db_session, other_client, org_id, project_id, ProjectRole.ADMIN)
    await grant_list_role(db_session, list_id, grace_id, ListRole.NONE)

    body = await page(other_client, f"/api/projects/{project_id}/audit")
    assert [event["action"] for event in body["events"]] == [
        "item.created",
        "list.created",
        "project.created",
    ]
    assert {event["list_id"] for event in body["events"]} == {open_list_id, None}
    response = await other_client.get(f"/api/lists/{list_id}/audit")
    assert response.status_code == 404, response.text
    # Ada, the organization owner, still sees everything.
    assert len((await page(client, f"/api/projects/{project_id}/audit"))["events"]) == 5


async def test_without_a_role_and_signed_out(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    urls = (f"/api/projects/{project_id}/audit", f"/api/lists/{list_id}/audit")

    for url in urls:
        response = await other_client.get(url)
        assert response.status_code == 401, response.text

    # A member of the organization without any grant.
    await join(db_session, other_client, org_id, project_id, None)
    for url in urls:
        response = await other_client.get(url)
        assert response.status_code == 404, response.text

    for url in (f"/api/projects/{uuid.uuid4()}/audit", f"/api/lists/{uuid.uuid4()}/audit"):
        response = await client.get(url)
        assert response.status_code == 404, response.text


async def test_organization_admin_reads_the_logs(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.ADMIN)

    assert len(await actions(other_client, f"/api/projects/{project_id}/audit")) == 2
    assert len(await actions(other_client, f"/api/lists/{list_id}/audit")) == 1


async def test_group_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    await sign_in(client)
    org_id, project_id, list_id, items_url = await ada_list(client)
    response = await client.patch(f"/api/lists/{list_id}", json={"mode": "mixed"})
    assert response.status_code == 200, response.text
    await create(client, items_url, "Buy domain")
    agent = await agent_item(db_session, org_id, list_id, "Write tests")
    grant = {"principal_kind": "agent", "principal_id": str(agent.id), "role": "editor"}
    response = await client.put(f"/api/lists/{list_id}/grants", json=grant)
    assert response.status_code == 200, response.text
    response = await client.put(f"/api/projects/{project_id}/grants", json=grant)
    assert response.status_code == 200, response.text

    project_url, list_url = f"/api/projects/{project_id}/audit", f"/api/lists/{list_id}/audit"
    for url in (project_url, list_url):
        assert await actions(client, url, group="items") == ["item.created", "item.created"]
        assert await actions(client, url, group="items", actor_kind="agent") == ["item.created"]
        # Both filters must hold.
        assert await actions(client, url, group="items", action="list.") == []
        response = await client.get(url, params={"group": "everything"})
        assert response.status_code == 422, response.text

    # The project's own events are with the lists.
    assert await actions(client, project_url, group="lists") == [
        "list.updated",
        "list.created",
        "project.created",
    ]
    assert await actions(client, list_url, group="lists") == ["list.updated", "list.created"]
    assert await actions(client, project_url, group="sharing") == [
        "project_grant.set",
        "list_grant.set",
    ]
    assert await actions(client, list_url, group="sharing") == ["list_grant.set"]


def test_every_action_is_in_a_group() -> None:
    assert all(action_group(action.value) is not None for action in AuditAction)
    assert action_group("list_grant.set") == "sharing"
    assert action_group("list.updated") == "lists"
    assert action_group("something.else") is None
