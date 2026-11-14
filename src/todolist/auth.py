"""The signed-in user: session helpers and the `current_user` dependency."""

import uuid
from typing import Annotated, Any

from fastapi import Depends, Request

from todolist.db import SessionDep
from todolist.errors import NotAuthenticatedError
from todolist.models import User

_SESSION_USER_KEY = "user_id"


def sign_in(request: Request, user: User) -> None:
    """Make `user` the session's user. Whatever the session held before is dropped."""
    request.session.clear()
    request.session[_SESSION_USER_KEY] = str(user.id)


def sign_out(request: Request) -> None:
    request.session.clear()


def _session_user_id(request: Request) -> uuid.UUID | None:
    value: Any = request.session.get(_SESSION_USER_KEY)
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def current_user(request: Request, session: SessionDep) -> User:
    """The session's user; 401 when nobody is signed in or the user no longer exists."""
    user_id = _session_user_id(request)
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None:
        request.session.clear()
        raise NotAuthenticatedError
    return user


# Use this in route signatures: `user: CurrentUser`.
CurrentUser = Annotated[User, Depends(current_user)]
