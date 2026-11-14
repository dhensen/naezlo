"""Serves the built single-page app (`frontend/dist`) from FastAPI.

In development the Vite dev server serves the frontend and proxies the backend paths here
(`frontend/vite.config.ts`). In production there is one process: this module adds a last
route that answers every GET the backend has no route for with a file from the build, or
with `index.html` so that React Router can handle the path (`/login`, `/oauth/consent`, ...).
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Match, Route
from starlette.types import Scope

from todolist.errors import NotFoundError

# Paths the backend owns. The frontend never gets them, also not when no backend route
# matches: `/api/unknown` stays a JSON 404 instead of becoming an HTML page.
# Keep this in step with `BACKEND_PATHS` in frontend/vite.config.ts.
BACKEND_PREFIXES = (
    "/api",
    "/authorize",
    "/token",
    "/register",
    "/revoke",
    "/.well-known",
    "/mcp",
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
)

# Vite puts the files with a content hash in their name here; they never change.
ASSETS_PREFIX = "assets/"
IMMUTABLE = "public, max-age=31536000, immutable"
# index.html names the current asset files, so the browser must ask again every time.
REVALIDATE = "no-cache"


def is_backend_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in BACKEND_PREFIXES)


class _FrontendRoute(Route):
    """Matches what is left for the frontend: a GET or HEAD outside the backend paths.

    Everything else does not match at all (not even partially, which would turn a POST to an
    unknown path into a 405), so the backend's own 404 is unchanged.
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD"):
            return Match.NONE, {}
        if is_backend_path(scope["path"]):
            return Match.NONE, {}
        return super().matches(scope)


def _file_in(directory: Path, relative: str) -> Path | None:
    """The file `relative` inside `directory`, or None (also for a path that leaves it)."""
    try:
        candidate = (directory / relative).resolve()
        if candidate.is_relative_to(directory) and candidate.is_file():
            return candidate
    except OSError, ValueError:  # a NUL byte or an over-long name in the path
        pass
    return None


def install_frontend(app: FastAPI, dist: Path | None) -> bool:
    """Serve the frontend build in `dist` for every path the backend does not own.

    Call it after all other routes are added. Does nothing (and returns False) when there is
    no build, which is the normal case in development and in the backend tests.
    """
    if dist is None:
        return False
    directory = dist.resolve()
    index = directory / "index.html"
    if not index.is_file():
        return False

    async def serve(request: Request) -> Response:
        relative: str = request.path_params["path"]
        file = _file_in(directory, relative) if relative else None
        if file is not None and file != index:
            cache = IMMUTABLE if relative.startswith(ASSETS_PREFIX) else REVALIDATE
            return FileResponse(file, headers={"Cache-Control": cache})
        if relative.startswith(ASSETS_PREFIX):
            # A missing script or stylesheet (an old tab after a deploy) must not get HTML.
            raise NotFoundError()
        return FileResponse(index, headers={"Cache-Control": REVALIDATE})

    app.router.routes.append(
        _FrontendRoute("/{path:path}", endpoint=serve, include_in_schema=False)
    )
    return True
