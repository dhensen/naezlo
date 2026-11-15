"""Assignees: who can be assigned to an item, and lists where only the assignee completes it."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import add_in_savepoint, add_member, grant_list_role, sign_in
from tests.test_audit import all_events, last_event
from tests.test_items import ITEM_NOT_FOUND, ada_list, create, join
from tests.test_mcp import agent_token, grant_agent, make_list
from todolist.models import Item, ListRole, MembershipRole, PrincipalKind, ProjectRole

INVALID_ASSIGNEE = {
    "detail": "An item can only be assigned to someone who can change the items of its list",
    "code": "invalid_assignee",
}


def user(user_id: str, name: str) -> dict[str, str]:
    return {"kind": "user", "id": user_id, "name": name}


async def assign(client: AsyncClient, item_id: str, kind: str, principal_id: str) -> Any:
    return await client.put(
        f"/api/items/{item_id}/assignee", json={"kind": kind, "id": principal_id}
    )


async def ada_id(client: AsyncClient) -> str:
    return (await client.get("/api/me")).json()["user"]["id"]


async def test_a_new_item_has_no_assignee(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)

    item = await create(client, url)

    assert item["assignee"] is None
    assert (await client.get(url)).json()[0]["assignee"] is None


async def test_assign_an_item_to_yourself_and_to_someone_else(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    ada = await ada_id(client)
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    before = len(await all_events(db_session))

    mine = await assign(client, item["id"], "user", ada)
    assert mine.status_code == 200, mine.text
    assert mine.json()["assignee"] == user(ada, "Ada")
    event = await last_event(db_session)
    assert (event.action, event.target_id) == ("item.assigned", uuid.UUID(item["id"]))
    assert event.details == {
        "title": "Buy domain",
        "assignee": user(ada, "Ada"),
        "previous_assignee": None,
    }

    same = await assign(client, item["id"], "user", ada)
    assert same.status_code == 200, same.text
    assert len(await all_events(db_session)) == before + 1

    hers = await assign(other_client, item["id"], "user", grace)
    assert hers.status_code == 200, hers.text
    assert hers.json()["assignee"] == user(grace, "Grace")
    event = await last_event(db_session)
    assert event.actor_id == uuid.UUID(grace)
    assert event.details == {
        "title": "Buy domain",
        "assignee": user(grace, "Grace"),
        "previous_assignee": user(ada, "Ada"),
    }
    assert (await client.get(url)).json()[0]["assignee"] == user(grace, "Grace")
    assert (await client.get(f"/api/items/{item['id']}")).json()["assignee"] == user(grace, "Grace")


async def test_unassign_an_item(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, _, url = await ada_list(client)
    ada = await ada_id(client)
    item = await create(client, url)
    assert (await assign(client, item["id"], "user", ada)).status_code == 200
    before = len(await all_events(db_session))

    removed = await client.delete(f"/api/items/{item['id']}/assignee")
    assert removed.status_code == 200, removed.text
    assert removed.json()["assignee"] is None
    event = await last_event(db_session)
    assert event.action == "item.unassigned"
    assert event.details == {"title": "Buy domain", "previous_assignee": user(ada, "Ada")}

    again = await client.delete(f"/api/items/{item['id']}/assignee")
    assert again.status_code == 200, again.text
    assert len(await all_events(db_session)) == before + 1


async def test_only_someone_who_can_change_the_items_can_be_assigned(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    item = await create(client, url)

    viewer = await assign(client, item["id"], "user", grace)
    unknown = await assign(client, item["id"], "user", str(uuid.uuid7()))
    wrong_kind = await assign(client, item["id"], "agent", grace)

    for response in (viewer, unknown, wrong_kind):
        assert response.status_code == 422, response.text
        assert response.json() == INVALID_ASSIGNEE
    assert (await client.get(url)).json()[0]["assignee"] is None


async def test_assigning_needs_the_editor_role(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    ada = await ada_id(client)
    await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    await sign_in(third_client, "linus@example.com", "Linus")
    item = await create(client, url)

    assert (await assign(other_client, item["id"], "user", ada)).status_code == 403
    assert (await other_client.delete(f"/api/items/{item['id']}/assignee")).status_code == 403
    outsider = await assign(third_client, item["id"], "user", ada)
    assert (outsider.status_code, outsider.json()) == (404, ITEM_NOT_FOUND)


async def test_an_agent_can_be_assigned_when_the_list_is_open_to_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, _ = await agent_token(client)
    agent_id = authorized.agent["id"]
    mixed = await make_list(client, authorized.org_id, "Mixed", "mixed")
    human_only = await make_list(client, authorized.org_id, "People", "human_only")
    viewed = await make_list(client, authorized.org_id, "Viewed", "mixed")
    await grant_agent(db_session, mixed, agent_id, ListRole.EDITOR)
    await grant_agent(db_session, human_only, agent_id, ListRole.EDITOR)
    await grant_agent(db_session, viewed, agent_id, ListRole.VIEWER)
    items = {
        list_id: await create(client, f"/api/lists/{list_id}/items")
        for list_id in (mixed, human_only, viewed)
    }

    assigned = await assign(client, items[mixed]["id"], "agent", agent_id)
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["assignee"] == {
        "kind": "agent",
        "id": agent_id,
        "name": authorized.agent["name"],
    }
    for list_id in (human_only, viewed):
        refused = await assign(client, items[list_id]["id"], "agent", agent_id)
        assert (refused.status_code, refused.json()) == (422, INVALID_ASSIGNEE)


async def test_the_assignees_of_a_list_are_everyone_who_can_change_its_items(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    authorized, _ = await agent_token(client)
    org_id = authorized.org_id
    ada = await ada_id(client)
    list_id = await make_list(client, org_id, "Chores", "mixed")
    project_id = (await client.get(f"/api/lists/{list_id}")).json()["project_id"]
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    linus = (await sign_in(third_client, "linus@example.com", "Linus"))["user"]["id"]
    await add_member(db_session, org_id, linus, MembershipRole.MEMBER)
    await grant_list_role(db_session, list_id, linus, ListRole.VIEWER)
    url = f"/api/lists/{list_id}/assignees"

    without_agent = await client.get(url)
    await grant_agent(db_session, list_id, authorized.agent["id"], ListRole.EDITOR)
    with_agent = await other_client.get(url)

    assert without_agent.status_code == 200, without_agent.text
    assert without_agent.json() == [user(ada, "Ada"), user(grace, "Grace")]
    assert with_agent.json() == [
        user(ada, "Ada"),
        user(grace, "Grace"),
        {"kind": "agent", "id": authorized.agent["id"], "name": authorized.agent["name"]},
    ]

    # In an AI-only list people do not change items, so only the agent is left.
    assert (
        await client.patch(f"/api/lists/{list_id}", json={"mode": "ai_only"})
    ).status_code == 200
    assert [assignee["kind"] for assignee in (await client.get(url)).json()] == ["agent"]


async def test_an_assignee_who_lost_access_no_longer_holds_the_item(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, url = await ada_list(client)
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    assert (await assign(client, item["id"], "user", grace)).status_code == 200

    await grant_list_role(db_session, list_id, grace, ListRole.VIEWER)

    assert (await client.get(url)).json()[0]["assignee"] is None


async def test_an_assignee_is_a_kind_and_an_id_together(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, list_id, _ = await ada_list(client)
    ada = uuid.UUID(await ada_id(client))

    def item(**assignee: Any) -> Item:
        return Item(
            list_id=uuid.UUID(list_id),
            title="Half an assignee",
            position=1,
            created_by_kind=PrincipalKind.USER,
            created_by_id=ada,
            **assignee,
        )

    for half in ({"assignee_kind": PrincipalKind.USER}, {"assignee_id": ada}):
        with pytest.raises(IntegrityError, match="ck_items_assignee_kind_with_id"):
            await add_in_savepoint(db_session, item(**half))
    await add_in_savepoint(db_session, item(assignee_kind=PrincipalKind.USER, assignee_id=ada))


async def required_list(client: AsyncClient) -> tuple[str, str, str, str]:
    """`ada_list` with assignment required."""
    org_id, project_id, list_id, url = await ada_list(client)
    response = await client.patch(f"/api/lists/{list_id}", json={"assignment_required": True})
    assert response.status_code == 200, response.text
    assert response.json()["assignment_required"] is True
    return org_id, project_id, list_id, url


async def complete(client: AsyncClient, item_id: str) -> Any:
    return await client.patch(f"/api/items/{item_id}", json={"status": "done"})


async def test_a_list_is_created_and_changed_with_assignment_required(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, project_id, list_id, _ = await ada_list(client)
    lists_url = f"/api/projects/{project_id}/lists"

    default = (await client.get(f"/api/lists/{list_id}")).json()
    created = await client.post(lists_url, json={"name": "Strict", "assignment_required": True})
    switched = await client.patch(f"/api/lists/{list_id}", json={"assignment_required": True})
    event = await last_event(db_session)
    null = await client.patch(f"/api/lists/{list_id}", json={"assignment_required": None})

    assert default["assignment_required"] is False
    assert created.status_code == 201, created.text
    assert created.json()["assignment_required"] is True
    assert switched.json()["assignment_required"] is True
    assert event.action == "list.updated"
    assert event.details["changes"] == {"assignment_required": {"old": False, "new": True}}
    assert null.status_code == 422


async def test_without_assignment_required_anyone_completes_an_item(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    assert (await assign(client, item["id"], "user", grace)).status_code == 200

    done = await complete(client, item["id"])

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done"
    assert done.json()["assignee"] == user(grace, "Grace")


async def test_with_assignment_required_only_the_assignee_completes_an_item(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await required_list(client)
    grace = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    events = len(await all_events(db_session))

    unassigned = await complete(client, item["id"])
    assert unassigned.status_code == 409, unassigned.text
    assert unassigned.json()["code"] == "item_not_assigned"

    assert (await assign(client, item["id"], "user", grace)).status_code == 200
    someone_else = await complete(client, item["id"])
    assert someone_else.status_code == 409, someone_else.text
    assert someone_else.json() == {
        "code": "item_assigned_to_other",
        "detail": "This item is assigned to Grace. In this list only the assignee can "
        "complete an item.",
    }
    assert (await client.get(url)).json()[0]["status"] == "open"
    # Only the assignment was recorded.
    assert len(await all_events(db_session)) == events + 1

    hers = await complete(other_client, item["id"])
    assert hers.status_code == 200, hers.text
    assert hers.json()["status"] == "done"

    # Everything else stays open to every editor.
    reopened = await client.patch(f"/api/items/{item['id']}", json={"status": "open"})
    renamed = await client.patch(f"/api/items/{item['id']}", json={"title": "Buy the domain"})
    assert (reopened.status_code, renamed.status_code) == (200, 200)
    assert reopened.json()["status"] == "open"


async def test_a_person_cannot_complete_an_item_an_agent_picked_up(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    authorized, _ = await agent_token(client)
    list_id = await make_list(client, authorized.org_id, "Chores", "mixed")
    await grant_agent(db_session, list_id, authorized.agent["id"], ListRole.EDITOR)
    assert (
        await client.patch(f"/api/lists/{list_id}", json={"assignment_required": True})
    ).status_code == 200
    item = await create(client, f"/api/lists/{list_id}/items")
    assert (await assign(client, item["id"], "agent", authorized.agent["id"])).status_code == 200

    response = await complete(client, item["id"])

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "item_assigned_to_other"
    assert authorized.agent["name"] in response.json()["detail"]
