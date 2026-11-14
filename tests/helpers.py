"""Helpers shared by test modules."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import (
    ListGrant,
    ListRole,
    Membership,
    MembershipRole,
    PrincipalKind,
    ProjectGrant,
    ProjectRole,
)


async def sign_in(
    client: AsyncClient, email: str = "ada@example.com", name: str = "Ada"
) -> dict[str, Any]:
    """Sign `client` in through dev-login (creating the user on first use).

    Returns the same body as GET /api/me: `{"user": {...}, "organizations": [...]}`.
    """
    response = await client.post("/api/auth/dev-login", json={"email": email, "name": name})
    assert response.status_code == 200, response.text
    return response.json()


async def add_member(
    session: AsyncSession, organization_id: str, user_id: str, role: MembershipRole
) -> None:
    """Make an existing user a member of an organization (ids as the API returns them)."""
    session.add(
        Membership(
            organization_id=uuid.UUID(organization_id), user_id=uuid.UUID(user_id), role=role
        )
    )
    await session.flush()


async def grant_project_role(
    session: AsyncSession, project_id: str, user_id: str, role: ProjectRole
) -> None:
    """Give an existing user a role on a project (ids as the API returns them)."""
    session.add(
        ProjectGrant(
            project_id=uuid.UUID(project_id),
            principal_kind=PrincipalKind.USER,
            user_id=uuid.UUID(user_id),
            role=role,
        )
    )
    await session.flush()


async def grant_list_role(
    session: AsyncSession, list_id: str, user_id: str, role: ListRole
) -> None:
    """Give an existing user a role on a list (ids as the API returns them)."""
    session.add(
        ListGrant(
            list_id=uuid.UUID(list_id),
            principal_kind=PrincipalKind.USER,
            user_id=uuid.UUID(user_id),
            role=role,
        )
    )
    await session.flush()


async def add_in_savepoint(session: AsyncSession, instance: object) -> None:
    """Add and flush inside a savepoint, so a failure leaves the session usable.

    The add has to happen inside it: `begin_nested()` first flushes whatever is pending.
    """
    async with session.begin_nested():
        session.add(instance)
        await session.flush()
