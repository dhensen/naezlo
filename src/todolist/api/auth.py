"""Signing in and out: Google login, dev-login and logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, StringConstraints

from todolist.api.me import MeOut, build_me
from todolist.auth import safe_next_path, sign_in, sign_out
from todolist.config import SettingsDep
from todolist.db import SessionDep
from todolist.errors import NotFoundError
from todolist.google import GoogleClient, GoogleLoginError, GoogleUnavailableError
from todolist.services.users import GoogleAccountConflictError, get_or_create_user

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginIn(BaseModel):
    email: EmailStr
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def require_dev_login(settings: SettingsDep) -> None:
    if not settings.dev_login:
        # Same answer as an unknown route: a deployment without dev-login doesn't reveal it.
        raise NotFoundError


# The check is a dependency so that it runs before the body is validated: a disabled
# dev-login answers 404 to every request, never 422.
@router.post("/dev-login", dependencies=[Depends(require_dev_login)])
async def dev_login(body: DevLoginIn, request: Request, session: SessionDep) -> MeOut:
    """Sign in as any email address without a password. Exists only when `DEV_LOGIN=true`."""
    user = await get_or_create_user(session, body.email, body.name)
    sign_in(request, user)
    return await build_me(session, user)


# Where to go after a Google sign-in; kept in the session while the browser is at Google.
_SESSION_NEXT_KEY = "login_next"


def require_google(request: Request) -> GoogleClient:
    google: GoogleClient | None = request.app.state.google
    if google is None:
        # Same answer as an unknown route, like a disabled dev-login.
        raise NotFoundError
    return google


GoogleDep = Annotated[GoogleClient, Depends(require_google)]


def _login_error(code: str) -> RedirectResponse:
    """Send the browser back to the login page, which explains `code` to the person.

    These routes are opened by browser navigation, so a JSON error body would be shown raw.
    """
    return RedirectResponse(f"/login?error={code}", status_code=status.HTTP_302_FOUND)


@router.get("/google/login", status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
async def google_login(
    request: Request, google: GoogleDep, settings: SettingsDep, next: str | None = None
) -> Response:
    """Start a Google sign-in. `next` is the path to open afterwards (relative paths only)."""
    next_path = safe_next_path(next)
    if next_path is None:
        request.session.pop(_SESSION_NEXT_KEY, None)
    else:
        request.session[_SESSION_NEXT_KEY] = next_path
    try:
        return await google.authorize_redirect(request, settings.google_redirect_uri)
    except GoogleUnavailableError:
        return _login_error("google_unavailable")


@router.get("/google/callback", status_code=status.HTTP_302_FOUND, response_class=RedirectResponse)
async def google_callback(request: Request, google: GoogleDep, session: SessionDep) -> Response:
    """Where Google sends the browser back to: finish the sign-in and go to `next` or `/`."""
    next_path = safe_next_path(request.session.pop(_SESSION_NEXT_KEY, None))
    try:
        identity = await google.fetch_identity(request)
    except GoogleUnavailableError:
        return _login_error("google_unavailable")
    except GoogleLoginError:
        return _login_error("google_login_failed")
    if not identity.email_verified:
        return _login_error("email_not_verified")

    # Google accounts without a profile name are rare; the part before the @ stands in.
    name = identity.name or identity.email.split("@")[0]
    try:
        user = await get_or_create_user(
            session, identity.email, name, google_sub=identity.sub, avatar_url=identity.picture
        )
    except GoogleAccountConflictError:
        return _login_error("google_account_conflict")
    sign_in(request, user)
    return RedirectResponse(next_path or "/", status_code=status.HTTP_302_FOUND)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    sign_out(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
