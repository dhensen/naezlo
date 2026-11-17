"""Users: sign-in creates the user and their default organization."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.models import User, normalize_email
from naezlo.services.invitations import accept_pending_invitations
from naezlo.services.organizations import create_organization

_ORGANIZATION_NAME_SUFFIX = "'s organization"
# organizations.name holds 200 characters.
_ORGANIZATION_NAME_MAX_LENGTH = 200


# users.name and users.avatar_url column sizes.
_NAME_MAX_LENGTH = 200
_AVATAR_URL_MAX_LENGTH = 2048


class GoogleAccountConflictError(Exception):
    """The email belongs to a user who is linked to a different Google account."""


def default_organization_name(user_name: str) -> str:
    owner = user_name[: _ORGANIZATION_NAME_MAX_LENGTH - len(_ORGANIZATION_NAME_SUFFIX)]
    return f"{owner}{_ORGANIZATION_NAME_SUFFIX}"


async def get_or_create_user(
    session: AsyncSession,
    email: str,
    name: str,
    google_sub: str | None = None,
    avatar_url: str | None = None,
) -> User:
    """The user for a sign-in, created on first use.

    A user is found by `google_sub` when given, otherwise by email. A new user also gets a
    default organization ("<name>'s organization") with themselves as owner. An existing user
    without a `google_sub` is linked to the given one; their name and email are left as they
    are. A given `avatar_url` replaces the stored one. Pending invitations for the user's email
    become memberships, for new and existing users alike.

    Raises `GoogleAccountConflictError` when the email belongs to a user who is linked to
    another Google account.
    """
    if avatar_url is not None and len(avatar_url) > _AVATAR_URL_MAX_LENGTH:
        avatar_url = None

    user: User | None = None
    if google_sub is not None:
        user = await session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = await session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is not None and google_sub is not None:
            if user.google_sub is not None:
                # Found by email, not by sub: the address now belongs to another Google account.
                raise GoogleAccountConflictError
            user.google_sub = google_sub

    if user is not None:
        if avatar_url is not None:
            user.avatar_url = avatar_url
        await session.flush()
        await accept_pending_invitations(session, user)
        return user

    name = name[:_NAME_MAX_LENGTH]
    user = User(email=email, name=name, google_sub=google_sub, avatar_url=avatar_url)
    session.add(user)
    await session.flush()
    await create_organization(session, default_organization_name(name), user, slug_source=name)
    # After the default organization, so that one stays first in the user's list.
    await accept_pending_invitations(session, user)
    return user
