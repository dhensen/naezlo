"""Organizations: slugs, creation, and the organizations of a user."""

import re
import unicodedata
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.models import Membership, MembershipRole, Organization, User

# The column holds 100 characters; this leaves room for a "-<n>" suffix.
_SLUG_BASE_MAX_LENGTH = 80
_FALLBACK_SLUG = "org"


def slugify(text: str) -> str:
    """Lowercase ASCII letters and digits joined by single hyphens: "Zoë's team" → "zoe-s-team"."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:_SLUG_BASE_MAX_LENGTH].strip("-") or _FALLBACK_SLUG


async def unique_slug(session: AsyncSession, text: str) -> str:
    """A slug for `text` that no organization uses yet: "ada", then "ada-2", "ada-3", ..."""
    base = slugify(text)
    # `base` only contains [a-z0-9-], so it needs no LIKE escaping.
    taken = set(
        await session.scalars(
            select(Organization.slug).where(
                or_(Organization.slug == base, Organization.slug.like(f"{base}-%"))
            )
        )
    )
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


async def create_organization(
    session: AsyncSession, name: str, owner: User, *, slug_source: str | None = None
) -> Organization:
    """Create an organization with a unique slug and make `owner` its owner.

    The slug is derived from `slug_source`, or from the name when that is not given.
    """
    organization = Organization(name=name, slug=await unique_slug(session, slug_source or name))
    session.add(organization)
    # Linked through the relationship: the organization has no id until the flush.
    session.add(Membership(organization=organization, user_id=owner.id, role=MembershipRole.OWNER))
    await session.flush()
    return organization


async def list_user_organizations(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[Organization, MembershipRole]]:
    """The organizations a user is a member of with their role, oldest membership first."""
    rows = await session.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id)
        # Membership ids are UUIDv7, so this is the order in which the user joined.
        .order_by(Membership.id)
    )
    return [(organization, role) for organization, role in rows]


async def get_organization_membership(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Organization, Membership] | None:
    """The organization and the user's membership in it; None when the user is not a member
    (or the organization does not exist: callers must not tell these apart)."""
    row = (
        await session.execute(
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Organization.id == organization_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def can_manage_organization(role: MembershipRole) -> bool:
    """Owners and admins manage an organization: its name, members and everything in it."""
    return role in (MembershipRole.OWNER, MembershipRole.ADMIN)


async def rename_organization(
    session: AsyncSession, organization: Organization, name: str
) -> Organization:
    """Change the name. The slug stays what it is, so links keep working."""
    organization.name = name
    await session.flush()
    return organization
