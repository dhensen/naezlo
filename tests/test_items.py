"""Items: CRUD in a list, completing and reopening, ordering and the role each action needs."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import (
    add_in_savepoint,
    add_member,
    grant_list_role,
    grant_project_role,
    sign_in,
)
from todolist.models import (
    Agent,
    Item,
    ItemStatus,
    ListRole,
    MembershipRole,
    PrincipalKind,
    ProjectRole,
    TodoList,
)
from todolist.principals import Principal
from todolist.services.items import create_item, list_items, update_item

ITEM_NOT_FOUND = {"detail": "Item not found", "code": "not_found"}
LIST_NOT_FOUND = {"detail": "List not found", "code": "not_found"}


async def ada_list(client: AsyncClient) -> tuple[str, str, str, str]:
    """Sign Ada in and give her a project with a list; returns the organization id, the
    project id, the list id and the list's items URL."""
    ada = await sign_in(client)
    org_id = ada["organizations"][0]["id"]
    response = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    response = await client.post(f"/api/projects/{project_id}/lists", json={"name": "Launch"})
    assert response.status_code == 201, response.text
    list_id = response.json()["id"]
    return org_id, project_id, list_id, f"/api/lists/{list_id}/items"


async def create(
    client: AsyncClient, url: str, title: str = "Buy domain", **extra: Any
) -> dict[str, Any]:
    response = await client.post(url, json={"title": title, **extra})
    assert response.status_code == 201, response.text
    return response.json()


async def join(
    db_session: AsyncSession,
    other_client: AsyncClient,
    org_id: str,
    project_id: str,
    role: ProjectRole | None,
) -> str:
    """Sign Grace in on `other_client`, make her a member of the organization and give her
    `role` on the project (None: no grant). Returns her user id."""
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    grace_id = grace["user"]["id"]
    await add_member(db_session, org_id, grace_id, MembershipRole.MEMBER)
    if role is not None:
        await grant_project_role(db_session, project_id, grace_id, role)
    return grace_id


async def item_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Item)) or 0


async def test_create_returns_the_item(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, list_id, url = await ada_list(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]

    response = await client.post(url, json={"title": "  Buy domain ", "notes": " Ask Bob. "})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["list_id"] == list_id
    assert body["title"] == "Buy domain"
    assert body["notes"] == "Ask Bob."
    assert body["status"] == "open"
    assert body["position"] == 1
    assert body["created_by"] == {"kind": "user", "id": ada_id}
    assert body["completed_by"] is None
    assert body["completed_at"] is None
    assert body["created_at"]
    assert body["updated_at"]
    item = await db_session.get(Item, uuid.UUID(body["id"]))
    assert item is not None
    assert item.created_by_kind is PrincipalKind.USER
    assert str(item.created_by_id) == ada_id


async def test_create_without_notes_and_with_empty_notes(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)

    assert (await create(client, url))["notes"] is None
    assert (await create(client, url, notes="   "))["notes"] is None


@pytest.mark.parametrize(
    "body",
    [{}, {"title": ""}, {"title": "   "}, {"title": "x" * 501}, {"title": None}, {"notes": "n"}],
)
async def test_create_rejects_a_bad_title(client: AsyncClient, body: dict[str, Any]) -> None:
    _, _, _, url = await ada_list(client)

    response = await client.post(url, json=body)

    assert response.status_code == 422


async def test_items_are_listed_in_position_order(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, _, url = await ada_list(client)
    first = await create(client, url, "First")
    second = await create(client, url, "Second")
    third = await create(client, url, "Third")
    assert [first["position"], second["position"], third["position"]] == [1, 2, 3]

    response = await client.get(url)
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["First", "Second", "Third"]
    assert response.json()[0] == first

    # The order is the position, not the age.
    item = await db_session.get(Item, uuid.UUID(third["id"]))
    assert item is not None
    item.position = 0
    await db_session.flush()

    response = await client.get(url)
    assert [item["title"] for item in response.json()] == ["Third", "First", "Second"]


async def test_new_item_goes_after_the_last_one(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    await create(client, url, "First")
    second = await create(client, url, "Second")
    assert (await client.delete(f"/api/items/{second['id']}")).status_code == 204

    assert (await create(client, url, "Third"))["position"] == 2
    assert [item["title"] for item in (await client.get(url)).json()] == ["First", "Third"]


async def test_items_belong_to_their_list(client: AsyncClient) -> None:
    _, project_id, _, url = await ada_list(client)
    await create(client, url, "Here")
    response = await client.post(f"/api/projects/{project_id}/lists", json={"name": "Other"})
    other_url = f"/api/lists/{response.json()['id']}/items"

    assert (await client.get(other_url)).json() == []
    assert (await create(client, other_url, "There"))["position"] == 1
    assert [item["title"] for item in (await client.get(url)).json()] == ["Here"]


async def test_get_one_item(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    item = await create(client, url)

    response = await client.get(f"/api/items/{item['id']}")

    assert response.status_code == 200
    assert response.json() == item


async def test_patch_changes_only_what_is_sent(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    item = await create(client, url, notes="Ask Bob.")
    item_url = f"/api/items/{item['id']}"

    response = await client.patch(item_url, json={"title": " Buy the domain "})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Buy the domain"
    assert body["notes"] == "Ask Bob."
    assert body["status"] == "open"
    assert body["position"] == item["position"]

    response = await client.patch(item_url, json={"notes": "Ask Carol."})
    assert response.json()["notes"] == "Ask Carol."
    assert response.json()["title"] == "Buy the domain"

    response = await client.patch(item_url, json={"notes": None})
    assert response.status_code == 200
    assert response.json()["notes"] is None
    assert (await client.get(item_url)).json() == response.json()


@pytest.mark.parametrize(
    "body",
    [{"title": None}, {"title": " "}, {"title": "x" * 501}, {"status": None}, {"status": "later"}],
)
async def test_patch_rejects_bad_values(client: AsyncClient, body: dict[str, Any]) -> None:
    _, _, _, url = await ada_list(client)
    item = await create(client, url)

    response = await client.patch(f"/api/items/{item['id']}", json=body)

    assert response.status_code == 422


async def test_complete_and_reopen(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, _, url = await ada_list(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"

    response = await client.patch(item_url, json={"status": "done"})
    assert response.status_code == 200, response.text
    done = response.json()
    assert done["status"] == "done"
    assert done["completed_by"] == {"kind": "user", "id": ada_id}
    assert done["completed_at"] is not None
    assert (await client.get(item_url)).json() == done
    row = await db_session.get(Item, uuid.UUID(item["id"]))
    assert row is not None
    assert row.completed_by_kind is PrincipalKind.USER
    assert str(row.completed_by_id) == ada_id
    assert row.completed_at is not None

    response = await client.patch(item_url, json={"status": "open"})
    assert response.status_code == 200, response.text
    reopened = response.json()
    assert reopened["status"] == "open"
    assert reopened["completed_by"] is None
    assert reopened["completed_at"] is None
    await db_session.refresh(row)
    assert row.completed_by_kind is None
    assert row.completed_by_id is None
    assert row.completed_at is None


async def test_completing_a_done_item_keeps_the_first_completion(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    ada_id = (await client.get("/api/me")).json()["user"]["id"]
    await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"
    done = (await client.patch(item_url, json={"status": "done"})).json()

    response = await other_client.patch(item_url, json={"status": "done", "title": "Renamed"})

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["completed_by"] == {"kind": "user", "id": ada_id}
    assert response.json()["completed_at"] == done["completed_at"]


async def test_completion_records_who_did_it(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    grace_id = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)

    response = await other_client.patch(f"/api/items/{item['id']}", json={"status": "done"})

    assert response.json()["completed_by"] == {"kind": "user", "id": grace_id}
    assert response.json()["created_by"] == item["created_by"]


async def test_service_records_an_agent_as_the_actor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, _, list_id, url = await ada_list(client)
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    principal = Principal.for_agent(agent)
    todo_list = await db_session.get(TodoList, uuid.UUID(list_id))
    assert todo_list is not None
    await create(client, url, "By Ada")

    item = await create_item(db_session, principal, todo_list, " By Claude ", "  ")
    assert item.title == "By Claude"
    assert item.notes is None
    assert item.position == 2
    assert item.created_by_kind is PrincipalKind.AGENT
    assert item.created_by_id == agent.id

    item = await update_item(db_session, principal, item, status=ItemStatus.DONE)
    assert item.completed_by_kind is PrincipalKind.AGENT
    assert item.completed_by_id == agent.id
    assert item.completed_at is not None
    assert [i.title for i in await list_items(db_session, todo_list)] == ["By Ada", "By Claude"]

    body = (await client.get(url)).json()[1]
    assert body["created_by"] == {"kind": "agent", "id": str(agent.id)}
    assert body["completed_by"] == {"kind": "agent", "id": str(agent.id)}


async def test_delete(client: AsyncClient, db_session: AsyncSession) -> None:
    _, _, _, url = await ada_list(client)
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"

    response = await client.delete(item_url)

    assert response.status_code == 204
    assert await item_count(db_session) == 0
    assert (await client.get(item_url)).json() == ITEM_NOT_FOUND
    assert (await client.delete(item_url)).status_code == 404
    assert (await client.get(url)).json() == []


async def test_deleting_the_list_deletes_its_items(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, list_id, url = await ada_list(client)
    await create(client, url, "First")
    await create(client, url, "Second")

    assert (await client.delete(f"/api/lists/{list_id}")).status_code == 204

    db_session.expire_all()
    assert await item_count(db_session) == 0


async def test_viewer_reads_but_cannot_write(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"

    assert (await other_client.get(url)).json() == [item]
    assert (await other_client.get(item_url)).json() == item

    for response in (
        await other_client.post(url, json={"title": "Mine"}),
        await other_client.patch(item_url, json={"title": "Mine"}),
        await other_client.patch(item_url, json={"status": "done"}),
        await other_client.delete(item_url),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "forbidden"
    assert (await client.get(url)).json() == [item]


async def test_editor_can_do_everything(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    grace_id = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)

    item = await create(other_client, url, "Mine")
    assert item["created_by"] == {"kind": "user", "id": grace_id}
    item_url = f"/api/items/{item['id']}"
    assert (await other_client.patch(item_url, json={"title": "Ours"})).status_code == 200
    assert (await other_client.delete(item_url)).status_code == 204


async def test_without_a_role_the_items_do_not_exist(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"
    # Grace is a member of the organization, without a grant.
    await join(db_session, other_client, org_id, project_id, None)

    for response in (
        await other_client.get(url),
        await other_client.post(url, json={"title": "Mine"}),
    ):
        assert response.status_code == 404
        assert response.json() == LIST_NOT_FOUND
    for response in (
        await other_client.get(item_url),
        await other_client.patch(item_url, json={"title": "Mine"}),
        await other_client.delete(item_url),
    ):
        assert response.status_code == 404
        assert response.json() == ITEM_NOT_FOUND
    assert await item_count(db_session) == 1


async def test_list_grant_decides_over_the_project_role(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, url = await ada_list(client)
    grace_id = await join(db_session, other_client, org_id, project_id, ProjectRole.EDITOR)
    item = await create(client, url)
    item_url = f"/api/items/{item['id']}"

    await grant_list_role(db_session, list_id, grace_id, ListRole.VIEWER)

    assert (await other_client.get(item_url)).status_code == 200
    assert (await other_client.patch(item_url, json={"status": "done"})).status_code == 403
    assert (await other_client.post(url, json={"title": "Mine"})).status_code == 403


async def test_list_only_editor_can_work_on_items(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, url = await ada_list(client)
    grace_id = await join(db_session, other_client, org_id, project_id, None)
    await grant_list_role(db_session, list_id, grace_id, ListRole.EDITOR)

    item = await create(other_client, url, "Mine")
    response = await other_client.patch(f"/api/items/{item['id']}", json={"status": "done"})
    assert response.status_code == 200
    assert response.json()["completed_by"] == {"kind": "user", "id": grace_id}


async def test_unknown_ids_and_signed_out(client: AsyncClient) -> None:
    response = await client.get(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 401

    await ada_list(client)
    response = await client.get(f"/api/items/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json() == ITEM_NOT_FOUND
    assert (await client.get(f"/api/lists/{uuid.uuid4()}/items")).json() == LIST_NOT_FOUND
    assert (await client.patch("/api/items/nope", json={})).status_code == 422


async def test_completion_must_match_the_status(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, list_id, _ = await ada_list(client)
    ada_id = uuid.UUID((await client.get("/api/me")).json()["user"]["id"])

    def item(**extra: Any) -> Item:
        return Item(
            list_id=uuid.UUID(list_id),
            title="Bad",
            position=1,
            created_by_kind=PrincipalKind.USER,
            created_by_id=ada_id,
            **extra,
        )

    with pytest.raises(IntegrityError):
        await add_in_savepoint(db_session, item(status=ItemStatus.DONE))
    with pytest.raises(IntegrityError):
        await add_in_savepoint(
            db_session,
            item(
                status=ItemStatus.OPEN,
                completed_by_kind=PrincipalKind.USER,
                completed_by_id=ada_id,
                completed_at=func.now(),
            ),
        )
