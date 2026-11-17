"""Item order: moving items, and positions that stay 1 to n after a move, create or delete."""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import Agent, Item, PrincipalKind, ProjectRole, TodoList
from naezlo.principals import Principal
from naezlo.services.items import delete_item, list_items, move_item
from tests.helpers import add_in_savepoint, grant_project_role
from tests.test_items import ITEM_NOT_FOUND, ada_list, create, join

INVALID_BEFORE = {
    "detail": "before_item_id is not an item of this list",
    "code": "invalid_before_item",
}


async def ada_list_again(client: AsyncClient) -> tuple[str, str, str, str]:
    """A second list in Ada's project (she is signed in already)."""
    me = (await client.get("/api/me")).json()
    org_id = me["organizations"][0]["id"]
    project_id = (await client.get(f"/api/orgs/{org_id}/projects")).json()[0]["id"]
    response = await client.post(f"/api/projects/{project_id}/lists", json={"name": "Other"})
    assert response.status_code == 201, response.text
    list_id = response.json()["id"]
    return org_id, project_id, list_id, f"/api/lists/{list_id}/items"


async def five_items(client: AsyncClient, url: str) -> dict[str, dict[str, Any]]:
    """Items A to E in that order, by title."""
    return {title: await create(client, url, title) for title in "ABCDE"}


async def move(client: AsyncClient, item: dict[str, Any], before: dict[str, Any] | None) -> Any:
    response = await client.post(
        f"/api/items/{item['id']}/move",
        json={"before_item_id": None if before is None else before["id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def order(client: AsyncClient, url: str) -> str:
    """The titles of the list in order; checks that the positions are 1 to n."""
    items = (await client.get(url)).json()
    assert [item["position"] for item in items] == list(range(1, len(items) + 1))
    return "".join(item["title"] for item in items)


async def test_move_to_the_start(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    body = await move(client, items["D"], items["A"])
    assert body["id"] == items["D"]["id"]
    assert body["position"] == 1
    assert await order(client, url) == "DABCE"


async def test_move_to_the_middle(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    # Down: the item lands just before the given one.
    assert (await move(client, items["A"], items["D"]))["position"] == 3
    assert await order(client, url) == "BCADE"
    # Up.
    assert (await move(client, items["E"], items["C"]))["position"] == 2
    assert await order(client, url) == "BECAD"


async def test_move_to_the_end(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    assert (await move(client, items["B"], None))["position"] == 5
    assert await order(client, url) == "ACDEB"
    # The last item stays the last.
    assert (await move(client, items["B"], None))["position"] == 5
    assert await order(client, url) == "ACDEB"


async def test_moves_that_change_nothing(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    # Before the item that already follows it, and before itself.
    assert (await move(client, items["B"], items["C"])) == items["B"]
    assert (await move(client, items["B"], items["B"])) == items["B"]
    assert await order(client, url) == "ABCDE"

    _, _, _, single_url = await ada_list_again(client)
    only = await create(client, single_url, "Only")
    assert (await move(client, only, None))["position"] == 1


async def test_moving_before_an_item_of_another_list_is_a_422(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)
    _, _, _, other_url = await ada_list_again(client)
    elsewhere = await create(client, other_url, "Elsewhere")

    response = await client.post(
        f"/api/items/{items['A']['id']}/move", json={"before_item_id": elsewhere["id"]}
    )
    assert response.status_code == 422
    assert response.json() == INVALID_BEFORE
    assert await order(client, url) == "ABCDE"
    assert await order(client, other_url) == "Elsewhere"

    # An item that does not exist gets the same answer.
    response = await client.post(
        f"/api/items/{items['A']['id']}/move", json={"before_item_id": str(uuid.uuid4())}
    )
    assert response.status_code == 422
    assert response.json() == INVALID_BEFORE


async def test_move_validates_the_body(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)
    move_url = f"/api/items/{items['A']['id']}/move"

    # The field has to be there: an empty body moves nothing.
    assert (await client.post(move_url, json={})).status_code == 422
    assert (await client.post(move_url, json={"before_item_id": "nope"})).status_code == 422
    assert await order(client, url) == "ABCDE"

    response = await client.post(f"/api/items/{uuid.uuid4()}/move", json={"before_item_id": None})
    assert response.status_code == 404
    assert response.json() == ITEM_NOT_FOUND


async def test_move_needs_the_editor_role(
    client: AsyncClient,
    other_client: AsyncClient,
    third_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org_id, project_id, _, url = await ada_list(client)
    items = await five_items(client, url)
    move_url = f"/api/items/{items['A']['id']}/move"
    body = {"before_item_id": None}

    # Nobody is signed in on the third client.
    assert (await third_client.post(move_url, json=body)).status_code == 401

    # A member without a role cannot see the item.
    grace_id = await join(db_session, other_client, org_id, project_id, None)
    response = await other_client.post(move_url, json=body)
    assert response.status_code == 404
    assert response.json() == ITEM_NOT_FOUND

    await grant_project_role(db_session, project_id, grace_id, ProjectRole.VIEWER)
    response = await other_client.post(move_url, json=body)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert await order(client, url) == "ABCDE"

    response = await client.put(
        f"/api/projects/{project_id}/grants",
        json={"principal_kind": "user", "principal_id": grace_id, "role": "editor"},
    )
    assert response.status_code == 200, response.text
    response = await other_client.post(move_url, json=body)
    assert response.status_code == 200
    assert await order(client, url) == "BCDEA"


async def test_positions_stay_gap_free_after_delete_and_create(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    assert (await client.delete(f"/api/items/{items['B']['id']}")).status_code == 204
    assert await order(client, url) == "ACDE"
    assert (await client.delete(f"/api/items/{items['A']['id']}")).status_code == 204
    assert await order(client, url) == "CDE"
    assert (await client.delete(f"/api/items/{items['E']['id']}")).status_code == 204
    assert await order(client, url) == "CD"

    assert (await create(client, url, "F"))["position"] == 3
    await move(client, items["D"], None)
    assert await order(client, url) == "CFD"
    await move(client, items["D"], items["C"])
    assert (await client.delete(f"/api/items/{items['C']['id']}")).status_code == 204
    assert await order(client, url) == "DF"


async def test_a_move_changes_only_the_moved_items_updated_at(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)

    await move(client, items["A"], None)
    after = {item["title"]: item for item in (await client.get(url)).json()}
    for title in "BCDE":
        assert after[title]["updated_at"] == items[title]["updated_at"]
        assert after[title]["position"] == items[title]["position"] - 1


async def test_other_lists_keep_their_order(client: AsyncClient) -> None:
    _, _, _, url = await ada_list(client)
    items = await five_items(client, url)
    _, _, _, other_url = await ada_list_again(client)
    for title in "XYZ":
        await create(client, other_url, title)

    await move(client, items["E"], items["A"])
    assert (await client.delete(f"/api/items/{items['C']['id']}")).status_code == 204
    assert await order(client, url) == "EABD"
    assert await order(client, other_url) == "XYZ"


async def test_service_moves_and_deletes_as_an_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, _, list_id, url = await ada_list(client)
    await five_items(client, url)
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    principal = Principal.for_agent(agent)
    assert principal.kind is PrincipalKind.AGENT
    the_list = await db_session.get(TodoList, uuid.UUID(list_id))
    assert the_list is not None
    a, b, c, d, e = await list_items(db_session, the_list)

    moved = await move_item(db_session, principal, d, b.id)
    assert moved is d
    assert [item.title for item in await list_items(db_session, the_list)] == list("ADBCE")
    # The objects that were loaded before the move have their new positions.
    assert [item.position for item in (a, d, b, c, e)] == [1, 2, 3, 4, 5]

    await delete_item(db_session, principal, a)
    assert [item.position for item in (d, b, c, e)] == [1, 2, 3, 4]
    assert await order(client, url) == "DBCE"


async def test_two_items_cannot_have_the_same_position(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, list_id, url = await ada_list(client)
    first = await create(client, url, "First")
    duplicate = Item(
        list_id=uuid.UUID(list_id),
        title="Same place",
        position=first["position"],
        created_by_kind=PrincipalKind.USER,
        created_by_id=uuid.UUID(first["created_by"]["id"]),
    )

    # The constraint is deferred to the commit; ask for the check now.
    with pytest.raises(IntegrityError):
        await add_in_savepoint(db_session, duplicate, check_deferred=True)
