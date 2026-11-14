"""Helpers shared by test modules."""

from typing import Any

from httpx import AsyncClient


async def sign_in(
    client: AsyncClient, email: str = "ada@example.com", name: str = "Ada"
) -> dict[str, Any]:
    """Sign `client` in through dev-login (creating the user on first use).

    Returns the same body as GET /api/me: `{"user": {...}, "organizations": [...]}`.
    """
    response = await client.post("/api/auth/dev-login", json={"email": email, "name": name})
    assert response.status_code == 200, response.text
    return response.json()
