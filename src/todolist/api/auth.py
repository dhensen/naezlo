"""Signing in and out. Google login is added next to dev-login in US-005."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, EmailStr, StringConstraints

from todolist.api.me import MeOut, build_me
from todolist.auth import sign_in, sign_out
from todolist.config import SettingsDep
from todolist.db import SessionDep
from todolist.errors import NotFoundError
from todolist.services.users import get_or_create_user

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


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    sign_out(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
