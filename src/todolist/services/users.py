"""Users: sign-in creates the user and their default organization."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import User, normalize_email
from todolist.services.organizations import create_organization

_ORGANIZATION_NAME_SUFFIX = "'s organization"
# organizations.name holds 200 characters.
_ORGANIZATION_NAME_MAX_LENGTH = 200


def default_organization_name(user_name: str) -> str:
    owner = user_name[: _ORGANIZATION_NAME_MAX_LENGTH - len(_ORGANIZATION_NAME_SUFFIX)]
    return f"{owner}{_ORGANIZATION_NAME_SUFFIX}"


async def get_or_create_user(
    session: AsyncSession, email: str, name: str, google_sub: str | None = None
) -> User:
    """The user for a sign-in, created on first use.

    A user is found by `google_sub` when given, otherwise by email. A new user also gets a
    default organization ("<name>'s organization") with themselves as owner. An existing user
    without a `google_sub` is linked to the given one; their name is left as it is.
    """
    user: User | None = None
    if google_sub is not None:
        user = await session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = await session.scalar(select(User).where(User.email == normalize_email(email)))

    if user is not None:
        if google_sub is not None and user.google_sub is None:
            user.google_sub = google_sub
            await session.flush()
        return user

    user = User(email=email, name=name, google_sub=google_sub)
    session.add(user)
    await session.flush()
    await create_organization(session, default_organization_name(name), user, slug_source=name)
    return user
