"""The MCP read tools: list_projects, list_lists and get_list."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from mcp import Client
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import ListRole
from tests.helpers import sign_in
from tests.test_mcp import agent_token, grant_agent, make_list, mcp_client

READ_TOOLS = ("list_projects", "list_lists", "get_list")


async def call(mcp: Client, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await mcp.call_tool(tool, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


async def error_of(mcp: Client, tool: str, **arguments: Any) -> str:
    """The message of a tool call that must fail. The SDK puts `Error executing tool <name>: `
    in front of the tool's own message."""
    result = await mcp.call_tool(tool, arguments)
    assert result.is_error, result.structured_content
    [content] = result.content
    assert content.type == "text"
    assert "Traceback" not in content.text
    return content.text


async def project_of(client: AsyncClient, list_id: str) -> str:
    response = await client.get(f"/api/lists/{list_id}")
    assert response.status_code == 200, response.text
    return response.json()["project_id"]


async def grant_agent_project(
    client: AsyncClient, project_id: str, agent_id: str, role: str
) -> None:
    response = await client.put(
        f"/api/projects/{project_id}/grants",
        json={"principal_kind": "agent", "principal_id": agent_id, "role": role},
    )
    assert response.status_code in (200, 201), response.text


async def add_list(client: AsyncClient, project_id: str, name: str, mode: str) -> str:
    response = await client.post(
        f"/api/projects/{project_id}/lists", json={"name": name, "mode": mode}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def add_item(client: AsyncClient, list_id: str, title: str, *, done: bool = False) -> str:
    response = await client.post(f"/api/lists/{list_id}/items", json={"title": title})
    assert response.status_code == 201, response.text
    item_id = response.json()["id"]
    if done:
        completed = await client.patch(f"/api/items/{item_id}", json={"status": "done"})
        assert completed.status_code == 200, completed.text
    return item_id


async def test_every_read_tool_explains_itself(app: FastAPI, client: AsyncClient) -> None:
    _, token = await agent_token(client)

    async with mcp_client(app, token) as mcp:
        tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}

    assert set(READ_TOOLS) <= set(tools)
    for name in READ_TOOLS:
        assert tools[name].description, name
        for parameter, schema in tools[name].input_schema.get("properties", {}).items():
            assert schema.get("description"), f"{name}.{parameter}"
    assert tools["list_projects"].input_schema.get("properties", {}) == {}
    assert set(tools["list_lists"].input_schema["properties"]) == {"project_id"}
    assert tools["list_lists"].input_schema.get("required", []) == []
    get_list = tools["get_list"].input_schema
    assert set(get_list["properties"]) == {"list_id", "include_done"}
    assert get_list["required"] == ["list_id"]
    assert get_list["properties"]["list_id"] == {
        "type": "string",
        "format": "uuid",
        "title": "List Id",
        "description": get_list["properties"]["list_id"]["description"],
    }
    assert get_list["properties"]["include_done"]["type"] == "boolean"
    assert get_list["properties"]["include_done"]["default"] is False


async def test_list_projects_gives_the_projects_with_a_list_the_agent_sees(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    agent_id, org_id = authorized.agent["id"], authorized.org_id
    # Seen: through a grant on one list, and through a role on the project.
    by_list = await make_list(client, org_id, "By list", "mixed")
    await grant_agent(db_session, by_list, agent_id, ListRole.VIEWER)
    by_project = await make_list(client, org_id, "By project", "ai_only")
    await grant_agent_project(client, await project_of(client, by_project), agent_id, "editor")
    described = await client.patch(
        f"/api/projects/{await project_of(client, by_list)}", json={"description": "Chores"}
    )
    assert described.status_code == 200, described.text
    # Not seen: a role on a project whose only list is human-only, a project whose only list
    # is closed to the agent, one without lists and one nobody shared.
    people = await make_list(client, org_id, "People", "human_only")
    await grant_agent_project(client, await project_of(client, people), agent_id, "admin")
    closed = await make_list(client, org_id, "Closed", "mixed")
    await grant_agent_project(client, await project_of(client, closed), agent_id, "admin")
    await grant_agent(db_session, closed, agent_id, ListRole.NONE)
    empty = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Empty"})
    await grant_agent_project(client, empty.json()["id"], agent_id, "admin")
    await make_list(client, org_id, "Unshared", "mixed")

    async with mcp_client(app, token) as mcp:
        projects = (await call(mcp, "list_projects"))["projects"]

    assert projects == [
        {
            "id": await project_of(client, by_list),
            "name": "By list project",
            "description": "Chores",
        },
        {
            "id": await project_of(client, by_project),
            "name": "By project project",
            "description": None,
        },
    ]


async def test_list_projects_is_empty_without_any_grant(app: FastAPI, client: AsyncClient) -> None:
    authorized, token = await agent_token(client)
    await make_list(client, authorized.org_id, "Unshared", "mixed")

    async with mcp_client(app, token) as mcp:
        assert await call(mcp, "list_projects") == {"projects": []}
        assert await call(mcp, "list_lists") == {"lists": []}


async def test_list_lists_gives_the_lists_with_role_and_item_counts(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    agent_id, org_id = authorized.agent["id"], authorized.org_id
    # Project one: the agent is editor on the project, and viewer on one of its lists.
    first = await make_list(client, org_id, "First", "mixed")
    project_one = await project_of(client, first)
    await grant_agent_project(client, project_one, agent_id, "editor")
    second = await add_list(client, project_one, "Second", "ai_only")
    await grant_agent(db_session, second, agent_id, ListRole.VIEWER)
    # Human-only (whatever the grant) and a `none` grant: never there.
    people = await add_list(client, project_one, "People", "human_only")
    await grant_agent(db_session, people, agent_id, ListRole.ADMIN)
    closed = await add_list(client, project_one, "Closed", "mixed")
    await grant_agent(db_session, closed, agent_id, ListRole.NONE)
    # Project two: only a list grant.
    third = await make_list(client, org_id, "Third", "mixed")
    await grant_agent(db_session, third, agent_id, ListRole.ADMIN)
    await make_list(client, org_id, "Unshared", "mixed")
    await add_item(client, first, "Open one")
    await add_item(client, first, "Open two")
    await add_item(client, first, "Done one", done=True)
    await add_item(client, third, "Done two", done=True)

    async with mcp_client(app, token) as mcp:
        everything = (await call(mcp, "list_lists"))["lists"]
        of_project_one = (await call(mcp, "list_lists", project_id=project_one))["lists"]
        of_project_two = (
            await call(mcp, "list_lists", project_id=await project_of(client, third))
        )["lists"]

    assert everything == [
        {
            "id": first,
            "name": "First",
            "description": None,
            "mode": "mixed",
            "assignment_required": False,
            "project": {"id": project_one, "name": "First project"},
            "role": "editor",
            "open_item_count": 2,
            "done_item_count": 1,
        },
        {
            "id": second,
            "name": "Second",
            "description": None,
            "mode": "ai_only",
            "assignment_required": False,
            "project": {"id": project_one, "name": "First project"},
            "role": "viewer",
            "open_item_count": 0,
            "done_item_count": 0,
        },
        {
            "id": third,
            "name": "Third",
            "description": None,
            "mode": "mixed",
            "assignment_required": False,
            "project": {"id": await project_of(client, third), "name": "Third project"},
            "role": "admin",
            "open_item_count": 0,
            "done_item_count": 1,
        },
    ]
    assert of_project_one == everything[:2]
    assert of_project_two == everything[2:]


async def test_a_list_appears_when_it_stops_being_human_only(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    people = await make_list(client, authorized.org_id, "People", "human_only")
    await grant_agent(db_session, people, authorized.agent["id"], ListRole.EDITOR)

    async with mcp_client(app, token) as mcp:
        before = await call(mcp, "list_lists")
        hidden = await error_of(mcp, "get_list", list_id=people)
        changed = await client.patch(f"/api/lists/{people}", json={"mode": "mixed"})
        assert changed.status_code == 200, changed.text
        after = await call(mcp, "list_lists")
        shown = await call(mcp, "get_list", list_id=people)

    assert before == {"lists": []}
    assert "not found" in hidden
    assert [todo_list["id"] for todo_list in after["lists"]] == [people]
    assert shown["role"] == "editor"


async def test_list_lists_of_a_project_with_a_role_but_no_visible_list_is_empty(
    app: FastAPI, client: AsyncClient
) -> None:
    authorized, token = await agent_token(client)
    people = await make_list(client, authorized.org_id, "People", "human_only")
    project_id = await project_of(client, people)
    await grant_agent_project(client, project_id, authorized.agent["id"], "viewer")

    async with mcp_client(app, token) as mcp:
        assert await call(mcp, "list_lists", project_id=project_id) == {"lists": []}


async def test_list_lists_of_an_unknown_or_inaccessible_project_is_a_tool_error(
    app: FastAPI, client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    shared = await make_list(client, authorized.org_id, "Shared", "mixed")
    await grant_agent(db_session, shared, authorized.agent["id"], ListRole.VIEWER)
    unshared = await project_of(
        client, await make_list(client, authorized.org_id, "Unshared", "mixed")
    )
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    foreign = await project_of(
        other_client,
        await make_list(other_client, grace["organizations"][0]["id"], "Foreign", "mixed"),
    )
    unknown = str(uuid.uuid4())

    async with mcp_client(app, token) as mcp:
        errors = {
            project_id: await error_of(mcp, "list_lists", project_id=project_id)
            for project_id in (unshared, foreign, unknown)
        }
        malformed = await error_of(mcp, "list_lists", project_id="not-an-id")

    for project_id, message in errors.items():
        # The same answer, whether the project exists or not.
        assert message == (
            f"Error executing tool list_lists: Project {project_id} not found: "
            "it does not exist or you have no access to it. "
            "Call list_projects for the projects you can use."
        )
    assert "project_id" in malformed


async def test_get_list_gives_the_list_and_its_items_in_position_order(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token = await agent_token(client)
    list_id = await make_list(client, authorized.org_id, "Groceries", "mixed")
    await grant_agent(db_session, list_id, authorized.agent["id"], ListRole.VIEWER)
    milk = await add_item(client, list_id, "Milk")
    bread = await add_item(client, list_id, "Bread", done=True)
    eggs = await add_item(client, list_id, "Eggs")
    noted = await client.patch(f"/api/items/{milk}", json={"notes": "Two litres"})
    assert noted.status_code == 200, noted.text
    # Eggs first: the order is the position, not the age.
    moved = await client.post(f"/api/items/{eggs}/move", json={"before_item_id": milk})
    assert moved.status_code == 200, moved.text

    async with mcp_client(app, token) as mcp:
        open_only = await call(mcp, "get_list", list_id=list_id)
        explicit = await call(mcp, "get_list", list_id=list_id, include_done=False)
        everything = await call(mcp, "get_list", list_id=list_id, include_done=True)

    items = everything.pop("items")
    assert everything == {
        "id": list_id,
        "name": "Groceries",
        "description": None,
        "mode": "mixed",
        "assignment_required": False,
        "project": {"id": await project_of(client, list_id), "name": "Groceries project"},
        "role": "viewer",
        "open_item_count": 2,
        "done_item_count": 1,
    }
    assert [(item["id"], item["title"], item["status"], item["position"]) for item in items] == [
        (eggs, "Eggs", "open", 1),
        (milk, "Milk", "open", 2),
        (bread, "Bread", "done", 3),
    ]
    assert [item["notes"] for item in items] == [None, "Two litres", None]
    assert [item["completed_at"] is not None for item in items] == [False, False, True]
    assert all(item["created_at"] and item["updated_at"] for item in items)
    assert open_only == explicit == {**everything, "items": items[:2]}


async def test_get_list_reads_a_list_through_a_project_role(
    app: FastAPI, client: AsyncClient
) -> None:
    authorized, token = await agent_token(client)
    list_id = await make_list(client, authorized.org_id, "Robots", "ai_only")
    await grant_agent_project(
        client, await project_of(client, list_id), authorized.agent["id"], "admin"
    )

    async with mcp_client(app, token) as mcp:
        todo_list = await call(mcp, "get_list", list_id=list_id)

    assert (todo_list["role"], todo_list["mode"], todo_list["items"]) == ("admin", "ai_only", [])


@pytest.mark.parametrize("case", ["no_grant", "none_grant", "human_only", "foreign", "unknown"])
async def test_get_list_of_an_unknown_or_inaccessible_list_is_a_tool_error(
    app: FastAPI,
    client: AsyncClient,
    other_client: AsyncClient,
    db_session: AsyncSession,
    case: str,
) -> None:
    authorized, token = await agent_token(client)
    agent_id, org_id = authorized.agent["id"], authorized.org_id
    if case == "no_grant":
        list_id = await make_list(client, org_id, "Unshared", "mixed")
    elif case == "none_grant":
        list_id = await make_list(client, org_id, "Closed", "mixed")
        await grant_agent_project(client, await project_of(client, list_id), agent_id, "admin")
        await grant_agent(db_session, list_id, agent_id, ListRole.NONE)
    elif case == "human_only":
        list_id = await make_list(client, org_id, "People", "human_only")
        await grant_agent(db_session, list_id, agent_id, ListRole.ADMIN)
    elif case == "foreign":
        grace = await sign_in(other_client, "grace@example.com", "Grace")
        list_id = await make_list(other_client, grace["organizations"][0]["id"], "Foreign", "mixed")
    else:
        list_id = str(uuid.uuid4())
    if case not in ("foreign", "unknown"):
        await add_item(client, list_id, "Secret")

    async with mcp_client(app, token) as mcp:
        message = await error_of(mcp, "get_list", list_id=list_id)

    # The same answer in every case: it does not tell which lists exist.
    assert message == (
        f"Error executing tool get_list: List {list_id} not found: "
        "it does not exist or you have no access to it. "
        "Call list_lists for the lists you can use."
    )
    assert "Secret" not in message


async def test_a_malformed_or_missing_list_id_is_a_tool_error(
    app: FastAPI, client: AsyncClient
) -> None:
    _, token = await agent_token(client)

    async with mcp_client(app, token) as mcp:
        malformed = await error_of(mcp, "get_list", list_id="groceries")
        missing = await error_of(mcp, "get_list")
        # The server still answers after the errors.
        assert await call(mcp, "list_projects") == {"projects": []}

    assert "list_id" in malformed
    assert "list_id" in missing
