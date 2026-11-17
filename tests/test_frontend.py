"""FastAPI serving the built frontend (`Settings.frontend_dist`)."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from naezlo.app import create_app
from naezlo.config import Settings
from naezlo.frontend import is_backend_path

INDEX_HTML = '<!doctype html><html><body><div id="root"></div></body></html>'
SCRIPT = "console.log('app')"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """What `npm run build` leaves behind, in miniature."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML)
    (dist / "assets" / "index-abc123.js").write_text(SCRIPT)
    (dist / "robots.txt").write_text("User-agent: *\n")
    # Next to the build, not in it: must never be served.
    (tmp_path / "secret.txt").write_text("secret")
    return dist


@pytest.fixture
def settings(settings: Settings, dist: Path) -> Settings:
    # Replaces the fixture of conftest.py, so `app` and `client` serve this build.
    return settings.model_copy(update={"frontend_dist": dist})


def is_index(response_text: str) -> bool:
    return response_text == INDEX_HTML


@pytest.mark.parametrize(
    "path", ["/", "/login", "/oauth/consent?request=abc", "/projects/123/lists", "/index.html"]
)
async def test_frontend_paths_get_index_html(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert is_index(response.text)


async def test_assets_are_served_and_cached(client: AsyncClient) -> None:
    response = await client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.text == SCRIPT
    assert "javascript" in response.headers["content-type"]
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_other_files_of_the_build_are_served(client: AsyncClient) -> None:
    response = await client.get("/robots.txt")

    assert response.status_code == 200
    assert response.text == "User-agent: *\n"
    assert response.headers["cache-control"] == "no-cache"


async def test_missing_asset_is_404_not_html(client: AsyncClient) -> None:
    response = await client.get("/assets/index-old999.js")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found", "code": "not_found"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/unknown",
        "/api",
        "/.well-known/unknown",
        "/mcp/unknown",
        "/token/unknown",
        "/healthz/unknown",
    ],
)
async def test_unknown_backend_paths_stay_json_404(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Not Found"}


async def test_backend_routes_are_not_shadowed(client: AsyncClient) -> None:
    health = await client.get("/healthz")
    assert health.json() == {"status": "ok"}

    me = await client.get("/api/me")
    assert me.status_code == 401
    assert me.json()["code"] == "not_authenticated"

    metadata = await client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    assert "authorization_endpoint" in metadata.json()

    # No session: the OAuth authorization endpoint answers itself (an error page or a
    # redirect), never the SPA.
    authorize = await client.get("/authorize")
    assert not is_index(authorize.text)

    for path in ("/token", "/register", "/revoke"):
        response = await client.post(path)
        assert response.status_code == 400, path
        assert "error" in response.json()

    # The MCP endpoint wants a bearer token.
    mcp = await client.get("/mcp")
    assert mcp.status_code == 401
    assert "www-authenticate" in mcp.headers

    openapi = await client.get("/openapi.json")
    assert "paths" in openapi.json()


async def test_only_get_reaches_the_frontend(client: AsyncClient) -> None:
    response = await client.post("/login")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "/a%00b"]
)
async def test_paths_cannot_leave_the_build(client: AsyncClient, path: str) -> None:
    response = await client.get(path)

    assert "secret" not in response.text
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert is_index(response.text)


async def test_without_a_build_only_the_backend_answers(settings: Settings, tmp_path: Path) -> None:
    app = create_app(settings.model_copy(update={"frontend_dist": tmp_path / "missing"}))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        health = await client.get("/healthz")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert health.status_code == 200


def test_backend_paths() -> None:
    assert is_backend_path("/api")
    assert is_backend_path("/api/me")
    assert is_backend_path("/.well-known/oauth-protected-resource/mcp")
    assert is_backend_path("/mcp")
    # Only whole path segments count: these belong to the frontend.
    assert not is_backend_path("/apiary")
    assert not is_backend_path("/tokens")
    assert not is_backend_path("/")


def test_vite_proxies_every_backend_path_of_the_story() -> None:
    """The dev server and the production fallback must agree on what the backend owns."""
    config = (
        Path(__file__).resolve().parent.parent / "frontend" / "src" / "backendPaths.ts"
    ).read_text()

    for path in ("/api", "/authorize", "/token", "/register", "/revoke", "/.well-known", "/mcp"):
        assert f"'{path}'" in config
        assert is_backend_path(path)
