"""Google login. Google itself is replaced by a mock transport: nothing leaves the process."""

import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from joserfc import jwt
from joserfc.jwk import RSAKey
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.app import create_app
from naezlo.auth import safe_next_path
from naezlo.config import Settings
from naezlo.db import get_session
from naezlo.google import GOOGLE_METADATA_URL, GoogleClient
from naezlo.models import Organization, User
from tests.helpers import sign_in

CLIENT_ID = "test-client-id.apps.googleusercontent.com"
ISSUER = "https://accounts.google.com"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"


@pytest.fixture(scope="module")
def signing_key() -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": "test-key"})


class FakeGoogle:
    """Answers the three requests the app makes to Google and signs ID tokens itself."""

    def __init__(self, key: RSAKey) -> None:
        # `key` is published as the JWKS; `signing_key` signs the ID tokens.
        self.key = key
        self.signing_key = key
        # Set by `complete_login` before the callback is called.
        self.claims: dict[str, Any] = {}
        self.token_error: str | None = None
        self.token_requests: list[dict[str, list[str]]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == GOOGLE_METADATA_URL:
            return httpx2.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": AUTHORIZE_URL,
                    "token_endpoint": TOKEN_URL,
                    "jwks_uri": JWKS_URL,
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if url == JWKS_URL:
            return httpx2.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if url == TOKEN_URL and request.method == "POST":
            self.token_requests.append(parse_qs(request.content.decode()))
            if self.token_error is not None:
                return httpx2.Response(400, json={"error": self.token_error})
            id_token = jwt.encode(
                {"alg": "RS256", "kid": "test-key"}, self.claims, self.signing_key
            )
            return httpx2.Response(
                200,
                json={
                    "access_token": "test-access-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "id_token": id_token,
                },
            )
        raise AssertionError(f"Unexpected request to Google: {request.method} {url}")


@pytest.fixture
def fake_google(signing_key: RSAKey) -> FakeGoogle:
    return FakeGoogle(signing_key)


@pytest.fixture
def google_app(settings: Settings, db_session: AsyncSession, fake_google: FakeGoogle) -> FastAPI:
    app = create_app(
        settings.model_copy(
            update={"google_client_id": CLIENT_ID, "google_client_secret": "test-secret"}
        )
    )
    app.state.google = GoogleClient(
        CLIENT_ID, "test-secret", transport=httpx2.MockTransport(fake_google.handler)
    )

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
async def google_client(google_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=google_app), base_url="http://test"
    ) as client:
        yield client


async def start_login(client: AsyncClient, next: str | None = None) -> dict[str, str]:
    """Call the login endpoint and return the query parameters of the redirect to Google."""
    response = await client.get(
        "/api/auth/google/login", params={} if next is None else {"next": next}
    )
    assert response.status_code == 302, response.text
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == AUTHORIZE_URL
    return {key: values[0] for key, values in parse_qs(location.query).items()}


async def complete_login(
    client: AsyncClient,
    fake_google: FakeGoogle,
    *,
    next: str | None = None,
    **claims: Any,
) -> Any:
    """Run the whole flow: login redirect, then the callback as Google would call it."""
    params = await start_login(client, next)
    now = int(time.time())
    fake_google.claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "iat": now,
        "exp": now + 3600,
        "nonce": params["nonce"],
        "sub": "google-sub-ada",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Lovelace",
        "picture": "https://lh3.googleusercontent.com/a/ada",
        **claims,
    }
    return await client.get(
        "/api/auth/google/callback", params={"code": "test-code", "state": params["state"]}
    )


async def count(session: AsyncSession, model: type[User | Organization]) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_login_redirects_to_google_with_state(google_client: AsyncClient) -> None:
    params = await start_login(google_client)

    assert params["client_id"] == CLIENT_ID
    assert params["response_type"] == "code"
    assert params["redirect_uri"] == "http://localhost:8000/api/auth/google/callback"
    assert set(params["scope"].split()) == {"openid", "email", "profile"}
    assert params["state"]
    assert params["nonce"]
    assert params["code_challenge_method"] == "S256"


async def test_new_user_is_created_and_signed_in(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    response = await complete_login(google_client, fake_google, email="Ada@Example.com")

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    me = (await google_client.get("/api/me")).json()
    assert me["user"]["email"] == "ada@example.com"
    assert me["user"]["name"] == "Ada Lovelace"
    assert me["user"]["avatar_url"] == "https://lh3.googleusercontent.com/a/ada"
    assert [(o["slug"], o["role"]) for o in me["organizations"]] == [("ada-lovelace", "owner")]
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.google_sub == "google-sub-ada"
    # The code was exchanged with the PKCE verifier and the registered redirect URI.
    [token_request] = fake_google.token_requests
    assert token_request["code"] == ["test-code"]
    assert token_request["redirect_uri"] == ["http://localhost:8000/api/auth/google/callback"]
    assert token_request["code_verifier"]


async def test_returning_user_is_found_by_sub(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    await complete_login(google_client, fake_google)
    first = (await google_client.get("/api/me")).json()
    await google_client.post("/api/auth/logout")

    # Same Google account; the name, address and picture changed at Google since.
    response = await complete_login(
        google_client,
        fake_google,
        email="ada.new@example.com",
        name="Ada King",
        picture="https://lh3.googleusercontent.com/a/new",
    )

    assert response.status_code == 302
    second = (await google_client.get("/api/me")).json()
    assert second["user"]["id"] == first["user"]["id"]
    assert second["user"]["email"] == "ada@example.com"
    assert second["user"]["name"] == "Ada Lovelace"
    assert second["user"]["avatar_url"] == "https://lh3.googleusercontent.com/a/new"
    assert second["organizations"] == first["organizations"]
    assert await count(db_session, User) == 1
    assert await count(db_session, Organization) == 1


async def test_existing_user_without_sub_is_linked(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    # dev-login is on in the test settings: this user has no google_sub yet.
    existing = await sign_in(google_client, email="ada@example.com", name="Ada")
    await google_client.post("/api/auth/logout")

    response = await complete_login(google_client, fake_google, email="ADA@example.com")

    assert response.status_code == 302
    me = (await google_client.get("/api/me")).json()
    assert me["user"]["id"] == existing["user"]["id"]
    assert me["user"]["name"] == "Ada"
    assert me["organizations"] == existing["organizations"]
    assert await count(db_session, User) == 1
    user = (await db_session.execute(select(User))).scalar_one()
    assert user.google_sub == "google-sub-ada"


async def test_email_linked_to_another_google_account_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    await complete_login(google_client, fake_google)
    await google_client.post("/api/auth/logout")

    response = await complete_login(google_client, fake_google, sub="another-google-account")

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=google_account_conflict"
    assert (await google_client.get("/api/me")).status_code == 401
    assert await count(db_session, User) == 1


@pytest.mark.parametrize("email_verified", [False, "true", None])
async def test_unverified_email_is_rejected(
    google_client: AsyncClient,
    db_session: AsyncSession,
    fake_google: FakeGoogle,
    email_verified: Any,
) -> None:
    response = await complete_login(google_client, fake_google, email_verified=email_verified)

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=email_not_verified"
    assert (await google_client.get("/api/me")).status_code == 401
    assert await count(db_session, User) == 0


async def test_relative_next_is_followed(
    google_client: AsyncClient, fake_google: FakeGoogle
) -> None:
    response = await complete_login(google_client, fake_google, next="/orgs/ada?tab=members")

    assert response.headers["location"] == "/orgs/ada?tab=members"


@pytest.mark.parametrize(
    "next",
    ["https://evil.example.com/", "//evil.example.com", "/\\evil.example.com", "orgs/ada"],
)
async def test_absolute_next_is_ignored(
    google_client: AsyncClient, fake_google: FakeGoogle, next: str
) -> None:
    response = await complete_login(google_client, fake_google, next=next)

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert (await google_client.get("/api/me")).status_code == 200


async def test_next_of_an_earlier_attempt_is_forgotten(
    google_client: AsyncClient, fake_google: FakeGoogle
) -> None:
    await start_login(google_client, next="/first")

    response = await complete_login(google_client, fake_google)

    assert response.headers["location"] == "/"


def test_safe_next_path() -> None:
    assert safe_next_path("/a/b?c=d#e") == "/a/b?c=d#e"
    assert safe_next_path(None) is None
    assert safe_next_path("") is None
    assert safe_next_path("/a\nb") is None


async def test_callback_with_wrong_state_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    await start_login(google_client)

    response = await google_client.get(
        "/api/auth/google/callback", params={"code": "test-code", "state": "not-the-state"}
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=google_login_failed"
    assert fake_google.token_requests == []
    assert await count(db_session, User) == 0


async def test_callback_in_another_browser_is_rejected(
    google_app: FastAPI, google_client: AsyncClient, fake_google: FakeGoogle
) -> None:
    params = await start_login(google_client)

    # The state is valid, but this browser's session never started the flow.
    async with AsyncClient(
        transport=ASGITransport(app=google_app), base_url="http://test"
    ) as other:
        response = await other.get(
            "/api/auth/google/callback", params={"code": "test-code", "state": params["state"]}
        )

    assert response.headers["location"] == "/login?error=google_login_failed"
    assert fake_google.token_requests == []


async def test_state_cannot_be_used_twice(
    google_client: AsyncClient, fake_google: FakeGoogle
) -> None:
    first = await complete_login(google_client, fake_google)
    assert first.headers["location"] == "/"
    await google_client.post("/api/auth/logout")

    replay = await google_client.get(str(first.request.url))

    assert replay.headers["location"] == "/login?error=google_login_failed"
    assert (await google_client.get("/api/me")).status_code == 401


async def test_id_token_with_wrong_nonce_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    response = await complete_login(google_client, fake_google, nonce="not-the-nonce")

    assert response.headers["location"] == "/login?error=google_login_failed"
    assert await count(db_session, User) == 0


async def test_id_token_for_another_client_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    response = await complete_login(google_client, fake_google, aud="someone-else")

    assert response.headers["location"] == "/login?error=google_login_failed"
    assert await count(db_session, User) == 0


async def test_id_token_signed_by_another_key_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    # Same key id as the published key, but not the key Google published.
    fake_google.signing_key = RSAKey.generate_key(2048, parameters={"kid": "test-key"})

    response = await complete_login(google_client, fake_google, sub="forged")

    assert response.headers["location"] == "/login?error=google_login_failed"
    assert await count(db_session, User) == 0


async def test_refusal_at_google_is_rejected(google_client: AsyncClient) -> None:
    params = await start_login(google_client)

    # What Google sends when the person presses "Cancel" on the consent page.
    response = await google_client.get(
        "/api/auth/google/callback", params={"error": "access_denied", "state": params["state"]}
    )

    assert response.headers["location"] == "/login?error=google_login_failed"


async def test_failed_token_exchange_is_rejected(
    google_client: AsyncClient, db_session: AsyncSession, fake_google: FakeGoogle
) -> None:
    fake_google.token_error = "invalid_grant"

    response = await complete_login(google_client, fake_google)

    assert response.headers["location"] == "/login?error=google_login_failed"
    assert await count(db_session, User) == 0


async def test_unreachable_google_is_reported(google_app: FastAPI) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no network", request=request)

    google_app.state.google = GoogleClient(
        CLIENT_ID, "test-secret", transport=httpx2.MockTransport(handler)
    )
    async with AsyncClient(
        transport=ASGITransport(app=google_app), base_url="http://test"
    ) as client:
        response = await client.get("/api/auth/google/login")

    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=google_unavailable"


async def test_google_routes_are_404_when_not_configured(client: AsyncClient) -> None:
    for path in ("/api/auth/google/login", "/api/auth/google/callback?code=x&state=y"):
        response = await client.get(path)

        assert response.status_code == 404
        assert response.json() == {"detail": "Not found", "code": "not_found"}


@pytest.mark.parametrize(
    ("client_id", "client_secret", "enabled"),
    [
        (None, None, False),
        ("id", None, False),
        (None, "secret", False),
        ("", "", False),
        ("id", "secret", True),
    ],
)
async def test_config_reports_google_login(
    settings: Settings, client_id: str | None, client_secret: str | None, enabled: bool
) -> None:
    configured = settings.model_copy(
        update={"google_client_id": client_id, "google_client_secret": client_secret}
    )
    assert configured.google_login_enabled is enabled
    app = create_app(configured)
    assert (app.state.google is not None) is enabled

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/config")

    assert response.json()["google_login_enabled"] is enabled


def test_google_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example.com/")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.google_login_enabled is True
    assert settings.google_redirect_uri == "https://todo.example.com/api/auth/google/callback"
