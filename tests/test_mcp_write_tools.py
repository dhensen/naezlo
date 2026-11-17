"""The MCP write tools: add_item, update_item, complete_item, reopen_item, move_item,
delete_item, claim_item and release_item."""

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import AuditEvent, ListRole, PrincipalKind
from tests.test_audit import all_events
from tests.test_mcp import agent_token, grant_agent, make_list, mcp_client
from tests.test_mcp_read_tools import add_item, call, error_of
from tests.test_oauth_token import Authorized

WRITE_TOOLS = (
    "add_item",
    "update_item",
    "complete_item",
    "reopen_item",
    "move_item",
    "delete_item",
)
NEEDS_EDITOR = "This needs the editor role on the list"


async def shared_list(
    client: AsyncClient,
    db_session: AsyncSession,
    role: ListRole = ListRole.EDITOR,
    mode: str = "mixed",
) -> tuple[Authorized, str, str]:
    """Ada's agent with its token and a list it has `role` on: (authorized, token, list id)."""
    authorized, token = await agent_token(client)
    list_id = await make_list(client, authorized.org_id, "Chores", mode)
    await grant_agent(db_session, list_id, authorized.agent["id"], role)
    return authorized, token, list_id


async def api_items(client: AsyncClient, list_id: str) -> list[dict[str, Any]]:
    response = await client.get(f"/api/lists/{list_id}/items")
    assert response.status_code == 200, response.text
    return response.json()


async def titles(client: AsyncClient, list_id: str) -> list[str]:
    return [item["title"] for item in await api_items(client, list_id)]


async def events_since(session: AsyncSession, count: int) -> list[AuditEvent]:
    return (await all_events(session))[count:]


def assert_by_agent(event: AuditEvent, authorized: Authorized) -> None:
    assert event.actor_kind is PrincipalKind.AGENT
    assert event.actor_id == uuid.UUID(authorized.agent["id"])
    assert event.actor_name == authorized.agent["name"]
    assert event.organization_id == uuid.UUID(authorized.org_id)


async def test_every_write_tool_explains_itself(app: FastAPI, client: AsyncClient) -> None:
    _, token = await agent_token(client)

    async with mcp_client(app, token) as mcp:
        tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}

    assert set(WRITE_TOOLS) <= set(tools)
    for name in WRITE_TOOLS:
        assert tools[name].description, name
        assert "editor" in (tools[name].description or ""), name
        for parameter, schema in tools[name].input_schema["properties"].items():
            assert schema.get("description"), f"{name}.{parameter}"
    parameters = {
        name: (
            set(tools[name].input_schema["properties"]),
            tools[name].input_schema.get("required", []),
        )
        for name in WRITE_TOOLS
    }
    assert parameters == {
        "add_item": ({"list_id", "title", "notes"}, ["list_id", "title"]),
        "update_item": ({"item_id", "title", "notes"}, ["item_id"]),
        "complete_item": ({"item_id"}, ["item_id"]),
        "reopen_item": ({"item_id"}, ["item_id"]),
        "move_item": ({"item_id", "before_item_id"}, ["item_id"]),
        "delete_item": ({"item_id"}, ["item_id"]),
    }


async def test_add_item_appends_an_open_item_made_by_the_agent(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    await add_item(client, list_id, "Dishes")
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        plain = await call(mcp, "add_item", list_id=list_id, title="  Laundry ")
        noted = await call(mcp, "add_item", list_id=list_id, title="Bins", notes=" Thursday ")

    assert plain["title"] == "Laundry"
    assert plain["notes"] is None
    assert plain["status"] == "open"
    assert plain["position"] == 2
    assert plain["list_id"] == list_id
    assert plain["completed_at"] is None
    assert noted["notes"] == "Thursday"
    assert noted["position"] == 3
    items = await api_items(client, list_id)
    assert [item["title"] for item in items] == ["Dishes", "Laundry", "Bins"]
    assert items[1]["id"] == plain["id"]
    assert items[1]["created_by"] == {"kind": "agent", "id": authorized.agent["id"]}
    events = await events_since(db_session, before)
    assert [event.action for event in events] == ["item.created", "item.created"]
    for event, item in zip(events, (plain, noted), strict=True):
        assert_by_agent(event, authorized)
        assert event.target_id == uuid.UUID(item["id"])
        assert event.list_id == uuid.UUID(list_id)
        assert event.details["title"] == item["title"]


@pytest.mark.parametrize(
    "arguments",
    [{"title": "   "}, {"title": "x" * 501}, {"title": "Fine", "notes": "x" * 10001}, {}],
)
async def test_add_item_refuses_a_bad_title_or_notes(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession, arguments: dict[str, str]
) -> None:
    _, token, list_id = await shared_list(client, db_session)

    async with mcp_client(app, token) as mcp:
        result = await mcp.call_tool("add_item", {"list_id": list_id, **arguments})

    assert result.is_error
    assert await api_items(client, list_id) == []


async def test_update_item_changes_title_and_notes(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    item_id = await add_item(client, list_id, "Dishes")
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        renamed = await call(mcp, "update_item", item_id=item_id, title="Do the dishes")
        noted = await call(mcp, "update_item", item_id=item_id, notes="Pans too")
        both = await call(mcp, "update_item", item_id=item_id, title="Dishes", notes="")
        same = await call(mcp, "update_item", item_id=item_id, title="Dishes")
        nothing = await error_of(mcp, "update_item", item_id=item_id)

    assert (renamed["title"], renamed["notes"]) == ("Do the dishes", None)
    assert (noted["title"], noted["notes"]) == ("Do the dishes", "Pans too")
    assert (both["title"], both["notes"]) == ("Dishes", None)
    assert same["id"] == item_id
    assert same["status"] == "open"
    assert (
        nothing == "Error executing tool update_item: Nothing to change: pass title, notes or both."
    )
    [item] = await api_items(client, list_id)
    assert (item["title"], item["notes"]) == ("Dishes", None)
    events = await events_since(db_session, before)
    # Three changes; the call that changed nothing recorded nothing.
    assert [event.action for event in events] == ["item.updated"] * 3
    for event in events:
        assert_by_agent(event, authorized)
        assert event.target_id == uuid.UUID(item_id)
    assert events[0].details["changes"] == {"title": {"old": "Dishes", "new": "Do the dishes"}}
    assert events[1].details["changes"] == {"notes": {"old": None, "new": "Pans too"}}
    assert events[2].details["changes"] == {
        "title": {"old": "Do the dishes", "new": "Dishes"},
        "notes": {"old": "Pans too", "new": None},
    }


async def test_complete_and_reopen_item(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session, mode="ai_only")
    async with mcp_client(app, token) as mcp:
        item_id = (await call(mcp, "add_item", list_id=list_id, title="Dishes"))["id"]
        before = len(await all_events(db_session))

        done = await call(mcp, "complete_item", item_id=item_id)
        completed = (await api_items(client, list_id))[0]
        again = await call(mcp, "complete_item", item_id=item_id)
        reopened = await call(mcp, "reopen_item", item_id=item_id)
        still_open = await call(mcp, "reopen_item", item_id=item_id)

    assert done["status"] == "done"
    assert done["completed_at"] is not None
    assert completed["completed_by"] == {"kind": "agent", "id": authorized.agent["id"]}
    assert again["status"] == "done"
    assert again["completed_at"] == done["completed_at"]
    assert reopened["status"] == "open"
    assert reopened["completed_at"] is None
    assert still_open["status"] == "open"
    [item] = await api_items(client, list_id)
    assert item["status"] == "open"
    assert item["completed_by"] is None
    events = await events_since(db_session, before)
    assert [event.action for event in events] == ["item.completed", "item.reopened"]
    for event in events:
        assert_by_agent(event, authorized)
        assert event.target_id == uuid.UUID(item_id)


async def test_move_item_before_another_item_or_to_the_end(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    a = await add_item(client, list_id, "A")
    b = await add_item(client, list_id, "B")
    c = await add_item(client, list_id, "C")
    other_list = await make_list(client, authorized.org_id, "Other", "mixed")
    elsewhere = await add_item(client, other_list, "Elsewhere")
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        first = await call(mcp, "move_item", item_id=c, before_item_id=a)
        assert await titles(client, list_id) == ["C", "A", "B"]
        last = await call(mcp, "move_item", item_id=c)
        assert await titles(client, list_id) == ["A", "B", "C"]
        stays = await call(mcp, "move_item", item_id=b, before_item_id=c)
        wrong = await error_of(mcp, "move_item", item_id=a, before_item_id=elsewhere)
        unknown = await error_of(mcp, "move_item", item_id=a, before_item_id=str(uuid.uuid4()))

    assert (first["id"], first["position"]) == (c, 1)
    assert (last["id"], last["position"]) == (c, 3)
    assert (stays["id"], stays["position"]) == (b, 2)
    assert wrong == "Error executing tool move_item: before_item_id is not an item of this list"
    assert unknown == wrong
    assert await titles(client, list_id) == ["A", "B", "C"]
    events = await events_since(db_session, before)
    assert [event.action for event in events] == ["item.moved", "item.moved"]
    assert events[0].details["changes"] == {"position": {"old": 3, "new": 1}}
    assert events[1].details["changes"] == {"position": {"old": 1, "new": 3}}
    for event in events:
        assert_by_agent(event, authorized)
        assert event.target_id == uuid.UUID(c)


async def test_delete_item_removes_it_and_closes_the_gap(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    await add_item(client, list_id, "A")
    b = await add_item(client, list_id, "B")
    await add_item(client, list_id, "C")
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        deleted = await call(mcp, "delete_item", item_id=b)
        gone = await error_of(mcp, "delete_item", item_id=b)

    assert deleted == {"id": b, "list_id": list_id, "title": "B"}
    assert gone.startswith(f"Error executing tool delete_item: Item {b} not found")
    items = await api_items(client, list_id)
    assert [(item["title"], item["position"]) for item in items] == [("A", 1), ("C", 2)]
    [event] = await events_since(db_session, before)
    assert event.action == "item.deleted"
    assert event.target_id == uuid.UUID(b)
    assert event.details["title"] == "B"
    assert_by_agent(event, authorized)


async def test_a_viewer_agent_gets_a_clear_permission_error_from_every_write_tool(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token, list_id = await shared_list(client, db_session, ListRole.VIEWER)
    a = await add_item(client, list_id, "A")
    b = await add_item(client, list_id, "B", done=True)
    before = await api_items(client, list_id)
    events = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        # Reading works, so the list and its items exist for the agent.
        assert (await call(mcp, "get_list", list_id=list_id))["role"] == "viewer"
        errors = {
            "add_item": await error_of(mcp, "add_item", list_id=list_id, title="New"),
            "update_item": await error_of(mcp, "update_item", item_id=a, title="Changed"),
            "complete_item": await error_of(mcp, "complete_item", item_id=a),
            "reopen_item": await error_of(mcp, "reopen_item", item_id=b),
            "move_item": await error_of(mcp, "move_item", item_id=b, before_item_id=a),
            "delete_item": await error_of(mcp, "delete_item", item_id=a),
        }

    assert errors == {tool: f"Error executing tool {tool}: {NEEDS_EDITOR}" for tool in WRITE_TOOLS}
    assert await api_items(client, list_id) == before
    assert len(await all_events(db_session)) == events


@pytest.mark.parametrize("hidden", ["unshared", "human_only", "closed", "unknown"])
async def test_an_item_the_agent_cannot_see_is_not_found(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession, hidden: str
) -> None:
    authorized, token = await agent_token(client)
    agent_id = authorized.agent["id"]
    list_id = await make_list(
        client, authorized.org_id, "Hidden", "human_only" if hidden == "human_only" else "mixed"
    )
    item_id = await add_item(client, list_id, "Secret")
    if hidden == "human_only":
        await grant_agent(db_session, list_id, agent_id, ListRole.ADMIN)
    elif hidden == "closed":
        await grant_agent(db_session, list_id, agent_id, ListRole.NONE)
    elif hidden == "unknown":
        item_id = str(uuid.uuid4())
    before = await api_items(client, list_id)

    async with mcp_client(app, token) as mcp:
        errors = {
            "update_item": await error_of(mcp, "update_item", item_id=item_id, title="Changed"),
            "complete_item": await error_of(mcp, "complete_item", item_id=item_id),
            "reopen_item": await error_of(mcp, "reopen_item", item_id=item_id),
            "move_item": await error_of(mcp, "move_item", item_id=item_id),
            "delete_item": await error_of(mcp, "delete_item", item_id=item_id),
        }
        if hidden != "unknown":
            added = await error_of(mcp, "add_item", list_id=list_id, title="New")
            assert added.startswith(f"Error executing tool add_item: List {list_id} not found")

    for tool, error in errors.items():
        assert error == (
            f"Error executing tool {tool}: Item {item_id} not found: it does not exist or "
            "you have no access to its list. Call get_list for the items of a list."
        )
    assert await api_items(client, list_id) == before


async def test_the_audit_log_shows_the_agent_as_actor(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    by_ada = await add_item(client, list_id, "By Ada")

    async with mcp_client(app, token) as mcp:
        item_id = (await call(mcp, "add_item", list_id=list_id, title="By agent"))["id"]
        await call(mcp, "update_item", item_id=item_id, notes="Soon")
        await call(mcp, "complete_item", item_id=item_id)
        await call(mcp, "reopen_item", item_id=item_id)
        await call(mcp, "move_item", item_id=item_id, before_item_id=by_ada)
        await call(mcp, "delete_item", item_id=item_id)

    agent = {"kind": "agent", "id": authorized.agent["id"], "name": authorized.agent["name"]}
    log = await client.get(f"/api/lists/{list_id}/audit", params={"actor_kind": "agent"})
    assert log.status_code == 200, log.text
    # Newest first.
    events = log.json()["events"][::-1]
    assert [event["action"] for event in events] == [
        "item.created",
        "item.updated",
        "item.completed",
        "item.reopened",
        "item.moved",
        "item.deleted",
    ]
    for event in events:
        assert event["actor"] == agent
        assert event["target_kind"] == "item"
        assert event["target_id"] == item_id
        assert event["list_id"] == list_id
    everything = await client.get(f"/api/lists/{list_id}/audit", params={"action": "item."})
    actors = {event["actor"]["kind"] for event in everything.json()["events"]}
    assert actors == {"agent", "user"}


async def test_a_failed_tool_call_changes_nothing(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token, list_id = await shared_list(client, db_session)
    a = await add_item(client, list_id, "A")
    events = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        result = await mcp.call_tool("update_item", {"item_id": a, "title": "x" * 501})
        missing = await mcp.call_tool("complete_item", {})

    assert result.is_error
    assert missing.is_error
    assert await titles(client, list_id) == ["A"]
    assert len(await all_events(db_session)) == events


ASSIGNMENT_TOOLS = ("claim_item", "release_item")


async def assign_to_ada(client: AsyncClient, item_id: str) -> None:
    ada = (await client.get("/api/me")).json()["user"]["id"]
    response = await client.put(f"/api/items/{item_id}/assignee", json={"kind": "user", "id": ada})
    assert response.status_code == 200, response.text


async def require_assignment(client: AsyncClient, list_id: str) -> None:
    response = await client.patch(f"/api/lists/{list_id}", json={"assignment_required": True})
    assert response.status_code == 200, response.text


async def test_the_assignment_tools_explain_themselves(app: FastAPI, client: AsyncClient) -> None:
    _, token = await agent_token(client)

    async with mcp_client(app, token) as mcp:
        tools = {tool.name: tool for tool in (await mcp.list_tools()).tools}

    for name in ASSIGNMENT_TOOLS:
        assert "editor" in (tools[name].description or ""), name
        assert set(tools[name].input_schema["properties"]) == {"item_id"}
        assert tools[name].input_schema["properties"]["item_id"].get("description")
    assert "claim_item" in (tools["complete_item"].description or "")


async def test_an_agent_claims_and_releases_an_item(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, token, list_id = await shared_list(client, db_session)
    me = {"kind": "agent", "id": authorized.agent["id"], "name": authorized.agent["name"]}
    item_id = await add_item(client, list_id, "Dishes")
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        free = (await call(mcp, "get_list", list_id=list_id))["items"][0]
        claimed = await call(mcp, "claim_item", item_id=item_id)
        again = await call(mcp, "claim_item", item_id=item_id)
        listed = (await call(mcp, "get_list", list_id=list_id))["items"][0]
        seen_by_ada = (await api_items(client, list_id))[0]
        released = await call(mcp, "release_item", item_id=item_id)
        released_again = await call(mcp, "release_item", item_id=item_id)

    assert (free["assignee"], free["assigned_to_you"]) == (None, False)
    for result in (claimed, again, listed):
        assert (result["assignee"], result["assigned_to_you"]) == (me, True)
    assert seen_by_ada["assignee"] == me
    for result in (released, released_again):
        assert (result["assignee"], result["assigned_to_you"]) == (None, False)
    assigned, unassigned = await events_since(db_session, before)
    assert (assigned.action, unassigned.action) == ("item.assigned", "item.unassigned")
    assert_by_agent(assigned, authorized)
    assert_by_agent(unassigned, authorized)
    assert assigned.details["assignee"] == me


async def test_an_agent_leaves_an_item_of_someone_else_alone(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token, list_id = await shared_list(client, db_session)
    item_id = await add_item(client, list_id, "Dishes")
    await assign_to_ada(client, item_id)
    before = len(await all_events(db_session))

    async with mcp_client(app, token) as mcp:
        seen = (await call(mcp, "get_list", list_id=list_id))["items"][0]
        claim = await error_of(mcp, "claim_item", item_id=item_id)
        release = await error_of(mcp, "release_item", item_id=item_id)

    assert seen["assignee"]["name"] == "Ada"
    assert seen["assigned_to_you"] is False
    assert "This item is assigned to Ada" in claim
    assert "pick an item without an assignee" in claim
    assert "assigned to Ada, not to you" in release
    assert (await api_items(client, list_id))[0]["assignee"]["name"] == "Ada"
    assert await events_since(db_session, before) == []


async def test_claiming_needs_the_editor_role(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token, list_id = await shared_list(client, db_session, ListRole.VIEWER)
    item_id = await add_item(client, list_id, "Dishes")

    async with mcp_client(app, token) as mcp:
        for tool in ASSIGNMENT_TOOLS:
            assert NEEDS_EDITOR in await error_of(mcp, tool, item_id=item_id)
        unknown = await error_of(mcp, "claim_item", item_id=str(uuid.uuid7()))

    assert "not found" in unknown


async def test_in_a_list_with_assignment_required_an_agent_claims_before_it_completes(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    _, token, list_id = await shared_list(client, db_session)
    await require_assignment(client, list_id)
    dishes = await add_item(client, list_id, "Dishes")
    laundry = await add_item(client, list_id, "Laundry")
    await assign_to_ada(client, laundry)

    async with mcp_client(app, token) as mcp:
        listed = await call(mcp, "get_list", list_id=list_id)
        unclaimed = await error_of(mcp, "complete_item", item_id=dishes)
        hers = await error_of(mcp, "complete_item", item_id=laundry)
        await call(mcp, "claim_item", item_id=dishes)
        done = await call(mcp, "complete_item", item_id=dishes)

    assert listed["assignment_required"] is True
    assert "Nobody is assigned to this item" in unclaimed
    assert "Call claim_item" in unclaimed
    assert "This item is assigned to Ada" in hers
    assert "Leave this item to them" in hers
    assert (done["status"], done["assigned_to_you"]) == ("done", True)
    assert [item["status"] for item in await api_items(client, list_id)] == ["done", "open"]
