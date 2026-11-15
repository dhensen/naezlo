"""Audit events: every change to a project, list, item or grant records who did what."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import sign_in
from tests.test_items import ada_list, create, join
from todolist.models import (
    Agent,
    AuditAction,
    AuditEvent,
    ItemStatus,
    ListMode,
    PrincipalKind,
    Project,
    ProjectRole,
    TodoList,
    User,
)
from todolist.principals import Principal
from todolist.services.audit import changes, record_event
from todolist.services.items import create_item, update_item
from todolist.services.lists import create_list


async def all_events(session: AsyncSession) -> list[AuditEvent]:
    """Every event, oldest first (ids are UUIDv7; created_at is the same within one test,
    because a test is one transaction)."""
    return list(await session.scalars(select(AuditEvent).order_by(AuditEvent.id)))


async def last_event(session: AsyncSession) -> AuditEvent:
    return (await all_events(session))[-1]


async def actions(session: AsyncSession) -> list[str]:
    return [event.action for event in await all_events(session)]


async def ada(session: AsyncSession) -> User:
    return (await session.scalars(select(User).where(User.email == "ada@example.com"))).one()


def assert_by_ada(event: AuditEvent, user: User, org_id: str) -> None:
    assert event.organization_id == uuid.UUID(org_id)
    assert event.actor_kind is PrincipalKind.USER
    assert event.actor_id == user.id
    assert event.actor_name == "Ada"
    assert event.created_at is not None


async def test_project_events(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await sign_in(client)
    org_id = me["organizations"][0]["id"]
    user = await ada(db_session)

    response = await client.post(f"/api/orgs/{org_id}/projects", json={"name": "Website"})
    assert response.status_code == 201, response.text
    project_id = uuid.UUID(response.json()["id"])

    created = await last_event(db_session)
    assert_by_ada(created, user, org_id)
    assert created.action == "project.created"
    assert (created.target_kind, created.target_id) == ("project", project_id)
    assert created.project_id == project_id
    assert created.list_id is None
    assert created.details == {"name": "Website"}

    response = await client.patch(
        f"/api/projects/{project_id}", json={"name": "Site", "description": "The new one"}
    )
    assert response.status_code == 200, response.text
    updated = await last_event(db_session)
    assert_by_ada(updated, user, org_id)
    assert updated.action == "project.updated"
    assert (updated.target_kind, updated.target_id) == ("project", project_id)
    assert updated.project_id == project_id
    assert updated.details == {
        "name": "Site",
        "changes": {
            "name": {"old": "Website", "new": "Site"},
            "description": {"old": None, "new": "The new one"},
        },
    }

    # Only the field that changed is in the details.
    await client.patch(f"/api/projects/{project_id}", json={"name": "Site", "description": None})
    assert (await last_event(db_session)).details == {
        "name": "Site",
        "changes": {"description": {"old": "The new one", "new": None}},
    }

    response = await client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 204, response.text
    deleted = await last_event(db_session)
    assert_by_ada(deleted, user, org_id)
    assert deleted.action == "project.deleted"
    assert (deleted.target_kind, deleted.target_id) == ("project", project_id)
    assert deleted.project_id == project_id
    assert deleted.details == {"name": "Site"}

    # The events outlive the project.
    assert await db_session.get(Project, project_id) is None
    assert await actions(db_session) == [
        "project.created",
        "project.updated",
        "project.updated",
        "project.deleted",
    ]


async def test_update_that_changes_nothing_records_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, project_id, list_id, url = await ada_list(client)
    item = await create(client, url, "Buy domain")
    before = await actions(db_session)

    for path, body in [
        (f"/api/projects/{project_id}", {"name": " Website "}),
        (f"/api/lists/{list_id}", {"name": "Launch", "mode": "human_only"}),
        (f"/api/items/{item['id']}", {"title": "Buy domain", "notes": None, "status": "open"}),
    ]:
        response = await client.patch(path, json=body)
        assert response.status_code == 200, response.text
    response = await client.post(f"/api/items/{item['id']}/move", json={"before_item_id": None})
    assert response.status_code == 200, response.text

    assert await actions(db_session) == before


async def test_list_events(client: AsyncClient, db_session: AsyncSession) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    user = await ada(db_session)
    project_uuid, list_uuid = uuid.UUID(project_id), uuid.UUID(list_id)

    created = await last_event(db_session)
    assert_by_ada(created, user, org_id)
    assert created.action == "list.created"
    assert (created.target_kind, created.target_id) == ("list", list_uuid)
    assert (created.project_id, created.list_id) == (project_uuid, list_uuid)
    assert created.details == {"name": "Launch", "mode": "human_only"}

    response = await client.patch(
        f"/api/lists/{list_id}", json={"name": "Go live", "mode": "mixed"}
    )
    assert response.status_code == 200, response.text
    updated = await last_event(db_session)
    assert_by_ada(updated, user, org_id)
    assert updated.action == "list.updated"
    assert (updated.target_kind, updated.target_id) == ("list", list_uuid)
    assert (updated.project_id, updated.list_id) == (project_uuid, list_uuid)
    assert updated.details == {
        "name": "Go live",
        "changes": {
            "name": {"old": "Launch", "new": "Go live"},
            "mode": {"old": "human_only", "new": "mixed"},
        },
    }

    response = await client.patch(f"/api/lists/{list_id}", json={"mode": "ai_only"})
    assert response.status_code == 200, response.text
    assert (await last_event(db_session)).details == {
        "name": "Go live",
        "changes": {"mode": {"old": "mixed", "new": "ai_only"}},
    }

    response = await client.delete(f"/api/lists/{list_id}")
    assert response.status_code == 204, response.text
    deleted = await last_event(db_session)
    assert_by_ada(deleted, user, org_id)
    assert deleted.action == "list.deleted"
    assert (deleted.target_kind, deleted.target_id) == ("list", list_uuid)
    assert (deleted.project_id, deleted.list_id) == (project_uuid, list_uuid)
    assert deleted.details == {"name": "Go live"}

    # The events outlive the list, and the project.
    assert await db_session.get(TodoList, list_uuid) is None
    assert (await client.delete(f"/api/projects/{project_id}")).status_code == 204
    assert await actions(db_session) == [
        "project.created",
        "list.created",
        "list.updated",
        "list.updated",
        "list.deleted",
        "project.deleted",
    ]


async def test_item_events(client: AsyncClient, db_session: AsyncSession) -> None:
    org_id, project_id, list_id, url = await ada_list(client)
    user = await ada(db_session)
    project_uuid, list_uuid = uuid.UUID(project_id), uuid.UUID(list_id)
    first = await create(client, url, "Buy domain")
    item = await create(client, url, "Write copy")
    item_id = uuid.UUID(item["id"])
    item_url = f"/api/items/{item['id']}"

    async def check(action: str, details: dict[str, Any]) -> None:
        event = await last_event(db_session)
        assert_by_ada(event, user, org_id)
        assert event.action == action
        assert (event.target_kind, event.target_id) == ("item", item_id)
        assert (event.project_id, event.list_id) == (project_uuid, list_uuid)
        assert event.details == details

    await check("item.created", {"title": "Write copy"})

    response = await client.patch(item_url, json={"title": "Write texts", "notes": "Home page"})
    assert response.status_code == 200, response.text
    await check(
        "item.updated",
        {
            "title": "Write texts",
            "changes": {
                "title": {"old": "Write copy", "new": "Write texts"},
                "notes": {"old": None, "new": "Home page"},
            },
        },
    )

    assert (await client.patch(item_url, json={"status": "done"})).status_code == 200
    await check("item.completed", {"title": "Write texts"})

    assert (await client.patch(item_url, json={"status": "open"})).status_code == 200
    await check("item.reopened", {"title": "Write texts"})

    assignee = {"kind": "user", "id": str(user.id), "name": user.name}
    response = await client.put(f"{item_url}/assignee", json={"kind": "user", "id": str(user.id)})
    assert response.status_code == 200, response.text
    await check(
        "item.assigned",
        {"title": "Write texts", "assignee": assignee, "previous_assignee": None},
    )

    assert (await client.delete(f"{item_url}/assignee")).status_code == 200
    await check("item.unassigned", {"title": "Write texts", "previous_assignee": assignee})

    response = await client.post(f"{item_url}/move", json={"before_item_id": first["id"]})
    assert response.status_code == 200, response.text
    await check(
        "item.moved",
        {"title": "Write texts", "changes": {"position": {"old": 2, "new": 1}}},
    )

    assert (await client.delete(item_url)).status_code == 204
    await check("item.deleted", {"title": "Write texts"})

    assert (await actions(db_session))[-9:] == [
        "item.created",  # Buy domain
        "item.created",
        "item.updated",
        "item.completed",
        "item.reopened",
        "item.assigned",
        "item.unassigned",
        "item.moved",
        "item.deleted",
    ]


async def test_one_patch_that_edits_and_completes_records_both(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, _, _, url = await ada_list(client)
    item = await create(client, url, "Buy domain")

    response = await client.patch(
        f"/api/items/{item['id']}", json={"title": "Buy the domain", "status": "done"}
    )
    assert response.status_code == 200, response.text

    updated, completed = (await all_events(db_session))[-2:]
    assert updated.action == "item.updated"
    assert updated.details["changes"] == {"title": {"old": "Buy domain", "new": "Buy the domain"}}
    assert completed.action == "item.completed"
    assert completed.details == {"title": "Buy the domain"}


async def test_events_by_an_agent(client: AsyncClient, db_session: AsyncSession) -> None:
    org_id, project_id, _, _ = await ada_list(client)
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    project = await db_session.get(Project, uuid.UUID(project_id))
    assert project is not None
    claude = Principal.for_agent(agent)

    todo_list = await create_list(db_session, claude, project, "Agent work", None, ListMode.MIXED)
    item = await create_item(db_session, claude, todo_list, "Check links")
    await update_item(db_session, claude, item, status=ItemStatus.DONE)

    events = (await all_events(db_session))[-3:]
    assert [event.action for event in events] == ["list.created", "item.created", "item.completed"]
    for event in events:
        assert event.organization_id == agent.organization_id
        assert event.actor_kind is PrincipalKind.AGENT
        assert event.actor_id == agent.id
        assert event.actor_name == "Claude"
        assert event.project_id == project.id
        assert event.list_id == todo_list.id

    # The name is a snapshot: the event keeps it when the agent is renamed or deleted.
    agent.name = "Claude 2"
    await db_session.flush()
    await db_session.delete(agent)
    await db_session.flush()
    db_session.expire_all()
    assert [event.actor_name for event in (await all_events(db_session))[-3:]] == ["Claude"] * 3


async def test_project_grant_events(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, _ = await ada_list(client)
    user = await ada(db_session)
    grace_id = await join(db_session, other_client, org_id, project_id, None)
    grants_url = f"/api/projects/{project_id}/grants"
    grace = {"kind": "user", "id": grace_id, "name": "Grace"}
    body = {"principal_kind": "user", "principal_id": grace_id, "role": "viewer"}

    response = await client.put(grants_url, json=body)
    assert response.status_code == 200, response.text
    grant_id = response.json()["id"]

    async def check(action: str, details: dict[str, Any]) -> None:
        event = await last_event(db_session)
        assert_by_ada(event, user, org_id)
        assert event.action == action
        assert (event.target_kind, event.target_id) == ("project_grant", uuid.UUID(grant_id))
        assert (event.project_id, event.list_id) == (uuid.UUID(project_id), None)
        assert event.details == details

    await check("project_grant.set", {"principal": grace, "role": {"old": None, "new": "viewer"}})

    assert (await client.put(grants_url, json={**body, "role": "editor"})).status_code == 200
    await check(
        "project_grant.set", {"principal": grace, "role": {"old": "viewer", "new": "editor"}}
    )

    # The same role again is not a change.
    before = await actions(db_session)
    assert (await client.put(grants_url, json={**body, "role": "editor"})).status_code == 200
    assert await actions(db_session) == before

    assert (await client.delete(f"{grants_url}/{grant_id}")).status_code == 204
    await check("project_grant.revoked", {"principal": grace, "role": "editor"})


async def test_project_grant_event_for_an_agent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, _, _ = await ada_list(client)
    agent = Agent(organization_id=uuid.UUID(org_id), name="Claude")
    db_session.add(agent)
    await db_session.flush()
    grants_url = f"/api/projects/{project_id}/grants"

    response = await client.put(
        grants_url,
        json={"principal_kind": "agent", "principal_id": str(agent.id), "role": "editor"},
    )
    assert response.status_code == 200, response.text
    claude = {"kind": "agent", "id": str(agent.id), "name": "Claude"}
    assert (await last_event(db_session)).details == {
        "principal": claude,
        "role": {"old": None, "new": "editor"},
    }

    assert (await client.delete(f"{grants_url}/{response.json()['id']}")).status_code == 204
    revoked = await last_event(db_session)
    assert revoked.action == "project_grant.revoked"
    assert revoked.details == {"principal": claude, "role": "editor"}


async def test_list_grant_events(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, _ = await ada_list(client)
    user = await ada(db_session)
    grace_id = await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    grants_url = f"/api/lists/{list_id}/grants"
    grace = {"kind": "user", "id": grace_id, "name": "Grace"}
    body = {"principal_kind": "user", "principal_id": grace_id, "role": "editor"}

    response = await client.put(grants_url, json=body)
    assert response.status_code == 200, response.text
    grant_id = response.json()["id"]

    async def check(action: str, details: dict[str, Any]) -> None:
        event = await last_event(db_session)
        assert_by_ada(event, user, org_id)
        assert event.action == action
        assert (event.target_kind, event.target_id) == ("list_grant", uuid.UUID(grant_id))
        assert (event.project_id, event.list_id) == (uuid.UUID(project_id), uuid.UUID(list_id))
        assert event.details == details

    await check("list_grant.set", {"principal": grace, "role": {"old": None, "new": "editor"}})

    assert (await client.put(grants_url, json={**body, "role": "none"})).status_code == 200
    await check("list_grant.set", {"principal": grace, "role": {"old": "editor", "new": "none"}})

    before = await actions(db_session)
    assert (await client.put(grants_url, json={**body, "role": "none"})).status_code == 200
    assert await actions(db_session) == before

    assert (await client.delete(f"{grants_url}/{grant_id}")).status_code == 204
    await check("list_grant.revoked", {"principal": grace, "role": "none"})


async def test_failed_requests_record_nothing(
    client: AsyncClient, other_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_id, project_id, list_id, url = await ada_list(client)
    item = await create(client, url, "Buy domain")
    await join(db_session, other_client, org_id, project_id, ProjectRole.VIEWER)
    before = await actions(db_session)
    unknown = str(uuid.uuid4())
    item_url = f"/api/items/{item['id']}"
    stranger = {"principal_kind": "user", "principal_id": unknown, "role": "viewer"}

    attempts = [
        # Grace is a viewer: 403.
        (other_client, "PATCH", f"/api/projects/{project_id}", {"name": "Hers"}, 403),
        (other_client, "DELETE", f"/api/projects/{project_id}", None, 403),
        (other_client, "POST", f"/api/projects/{project_id}/lists", {"name": "Hers"}, 403),
        (other_client, "PATCH", f"/api/lists/{list_id}", {"mode": "mixed"}, 403),
        (other_client, "DELETE", f"/api/lists/{list_id}", None, 403),
        (other_client, "POST", url, {"title": "Hers"}, 403),
        (other_client, "PATCH", item_url, {"status": "done"}, 403),
        (other_client, "POST", f"{item_url}/move", {"before_item_id": None}, 403),
        (other_client, "DELETE", item_url, None, 403),
        (other_client, "PUT", f"/api/projects/{project_id}/grants", stranger, 403),
        (other_client, "PUT", f"/api/lists/{list_id}/grants", stranger, 403),
        # Ada may, but the request is wrong.
        (client, "POST", f"/api/orgs/{org_id}/projects", {"name": ""}, 422),
        (client, "PATCH", f"/api/projects/{project_id}", {"name": None}, 422),
        (client, "PATCH", f"/api/lists/{list_id}", {"mode": "robots"}, 422),
        (client, "POST", url, {"title": " "}, 422),
        (client, "PATCH", item_url, {"status": "later"}, 422),
        (client, "POST", f"{item_url}/move", {"before_item_id": unknown}, 422),
        (client, "PUT", f"/api/projects/{project_id}/grants", stranger, 422),
        (client, "PUT", f"/api/lists/{list_id}/grants", stranger, 422),
        (client, "DELETE", f"/api/projects/{project_id}/grants/{unknown}", None, 404),
        (client, "DELETE", f"/api/lists/{list_id}/grants/{unknown}", None, 404),
        (client, "DELETE", f"/api/items/{unknown}", None, 404),
    ]
    for who, method, path, body, status in attempts:
        response = await who.request(method, path, json=body)
        assert response.status_code == status, (method, path, response.text)

    assert await actions(db_session) == before


async def test_event_is_rolled_back_with_the_callers_transaction(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """record_event flushes but never commits: when the transaction of the change is rolled
    back (`get_session` does that for a request that raises), the event is gone too."""
    org_id, project_id, _, _ = await ada_list(client)
    user = await ada(db_session)
    principal = Principal.for_user(user, uuid.UUID(org_id))
    before = await db_session.scalar(select(func.count()).select_from(AuditEvent))

    savepoint = await db_session.begin_nested()
    event = await record_event(
        db_session,
        principal,
        AuditAction.PROJECT_UPDATED,
        target_kind="project",
        target_id=uuid.UUID(project_id),
        project_id=uuid.UUID(project_id),
    )
    assert event.details == {}
    in_transaction = await db_session.scalar(select(func.count()).select_from(AuditEvent))
    assert in_transaction == (before or 0) + 1
    await savepoint.rollback()

    assert await db_session.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_changes_keeps_only_what_differs() -> None:
    target = uuid.uuid4()
    old: dict[str, object] = {"name": "A", "mode": ListMode.MIXED, "owner": None, "same": 1}
    new: dict[str, object] = {"name": "B", "mode": ListMode.AI_ONLY, "owner": target, "same": 1}
    assert changes(old, new) == {
        "name": {"old": "A", "new": "B"},
        "mode": {"old": "mixed", "new": "ai_only"},
        "owner": {"old": None, "new": str(target)},
    }


async def test_audit_events_table(db_session: AsyncSession) -> None:
    rows = await db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'audit_events'")
    )
    indexes = {row.indexname: row.indexdef for row in rows}
    assert "(project_id, created_at)" in indexes["ix_audit_events_project_id_created_at"]
    assert "(list_id, created_at)" in indexes["ix_audit_events_list_id_created_at"]

    # Only the organization is a foreign key: nothing else can take an event with it.
    foreign_keys = (
        await db_session.scalars(
            text(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = 'audit_events'::regclass AND contype = 'f'"
            )
        )
    ).all()
    assert foreign_keys == ["fk_audit_events_organization_id_organizations"]
