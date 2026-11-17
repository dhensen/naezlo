"""Sessions, dev-login, logout, /api/me and /api/config."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.sessions import SessionMiddleware

from naezlo.app import create_app
from naezlo.config import DEV_SESSION_SECRET, Settings
from naezlo.db import get_session
from naezlo.models import Membership, Organization, User
from tests.helpers import sign_in


@pytest.fixture
async def client_without_dev_login(
    settings: Settings, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings.model_copy(update={"dev_login": False}))

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def count(session: AsyncSession, model: type[User | Organization | Membership]) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_first_login_creates_user_with_default_organization(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client, email="Ada@Example.com", name="Ada Lovelace")

    assert me["user"]["email"] == "ada@example.com"
    assert me["user"]["name"] == "Ada Lovelace"
    assert me["user"]["avatar_url"] is None
    assert [(o["name"], o["slug"], o["role"]) for o in me["organizations"]] == [
        ("Ada Lovelace's organization", "ada-lovelace", "owner")
    ]
    assert await count(db_session, User) == 1
    assert await count(db_session, Organization) == 1
    assert await count(db_session, Membership) == 1


async def test_second_login_creates_nothing(client: AsyncClient, db_session: AsyncSession) -> None:
    first = await sign_in(client)
    await client.post("/api/auth/logout")

    # Another spelling of the same address, and another name: still the same user.
    second = await sign_in(client, email=" ADA@example.com", name="Someone else")

    assert second == first
    assert await count(db_session, User) == 1
    assert await count(db_session, Organization) == 1
    assert await count(db_session, Membership) == 1


async def test_me_returns_the_signed_in_user(client: AsyncClient) -> None:
    signed_in = await sign_in(client)

    response = await client.get("/api/me")

    assert response.status_code == 200
    assert response.json() == signed_in
    assert set(response.json()["user"]) == {"id", "email", "name", "avatar_url"}
    assert set(response.json()["organizations"][0]) == {"id", "name", "slug", "role"}


async def test_me_is_401_when_signed_out(client: AsyncClient) -> None:
    response = await client.get("/api/me")

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not signed in", "code": "not_authenticated"}


async def test_me_is_401_with_a_forged_session_cookie(client: AsyncClient) -> None:
    client.cookies.set("session", "eyJ1c2VyX2lkIjogIjEyMyJ9.forged.signature")

    response = await client.get("/api/me")

    assert response.status_code == 401


async def test_me_is_401_when_the_user_no_longer_exists(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await sign_in(client)
    user = await db_session.get_one(User, me["user"]["id"])
    await db_session.delete(user)
    await db_session.flush()

    response = await client.get("/api/me")

    assert response.status_code == 401


async def test_logout_clears_the_session(client: AsyncClient) -> None:
    await sign_in(client)

    response = await client.post("/api/auth/logout")

    assert response.status_code == 204
    assert (await client.get("/api/me")).status_code == 401


async def test_logout_when_signed_out_is_fine(client: AsyncClient) -> None:
    assert (await client.post("/api/auth/logout")).status_code == 204


async def test_signing_in_as_someone_else_switches_the_user(client: AsyncClient) -> None:
    await sign_in(client, email="ada@example.com", name="Ada")
    await sign_in(client, email="grace@example.com", name="Grace")

    me = (await client.get("/api/me")).json()

    assert me["user"]["email"] == "grace@example.com"
    assert [o["slug"] for o in me["organizations"]] == ["grace"]


async def test_session_cookie_attributes(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/dev-login", json={"email": "ada@example.com", "name": "Ada"}
    )

    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("session=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    # Tests and local development run on plain http.
    assert "secure" not in cookie


def test_session_cookie_is_secure_in_production() -> None:
    settings = Settings(_env_file=None, environment="production", session_secret="x" * 32)  # pyright: ignore[reportCallIssue]

    app: FastAPI = create_app(settings)

    session_middleware = next(m for m in app.user_middleware if m.cls is SessionMiddleware)
    assert session_middleware.kwargs["https_only"] is True
    assert session_middleware.kwargs["same_site"] == "lax"


async def test_dev_login_is_404_when_disabled(
    client_without_dev_login: AsyncClient, db_session: AsyncSession
) -> None:
    response = await client_without_dev_login.post(
        "/api/auth/dev-login", json={"email": "ada@example.com", "name": "Ada"}
    )

    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert await count(db_session, User) == 0
    assert (await client_without_dev_login.get("/api/me")).status_code == 401


async def test_dev_login_is_404_when_disabled_even_for_an_invalid_body(
    client_without_dev_login: AsyncClient,
) -> None:
    response = await client_without_dev_login.post("/api/auth/dev-login", json={})

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "name": "Ada"},
        {"email": "ada@example.com", "name": "   "},
        {"email": "ada@example.com"},
    ],
)
async def test_dev_login_rejects_invalid_input(client: AsyncClient, body: dict[str, str]) -> None:
    response = await client.post("/api/auth/dev-login", json=body)

    assert response.status_code == 422


async def test_config_is_public(client: AsyncClient, settings: Settings) -> None:
    response = await client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "dev_login_enabled": True,
        "google_login_enabled": False,
        "mcp_url": f"{settings.public_base_url.rstrip('/')}/mcp",
    }


async def test_config_reports_dev_login_disabled(client_without_dev_login: AsyncClient) -> None:
    response = await client_without_dev_login.get("/api/config")

    assert response.json()["dev_login_enabled"] is False


def test_dev_login_is_off_by_default() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.dev_login is False
    assert settings.session_secret == DEV_SESSION_SECRET


def test_production_requires_a_session_secret() -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(_env_file=None, environment="production")  # pyright: ignore[reportCallIssue]


def test_production_refuses_dev_login() -> None:
    with pytest.raises(ValueError, match="DEV_LOGIN"):
        Settings(_env_file=None, environment="production", session_secret="x" * 32, dev_login=True)  # pyright: ignore[reportCallIssue]
