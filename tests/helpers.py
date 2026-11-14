"""Helpers shared by test modules."""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Membership, MembershipRole


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
