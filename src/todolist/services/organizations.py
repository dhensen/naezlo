"""Organizations: slugs, creation, the organizations of a user, and member management."""

import re
import unicodedata
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import ConflictError, ForbiddenError, NotFoundError
from todolist.models import (
    Membership,
    MembershipRole,
    Organization,
    Project,
    ProjectGrant,
    User,
)

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


async def list_members(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[tuple[Membership, User]]:
    """The memberships of an organization with their users, in the order they joined."""
    rows = await session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(Membership.id)
    )
    return [(membership, user) for membership, user in rows]


async def _get_member(
    session: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Membership, User]:
    row = (
        await session.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.organization_id == organization_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Member not found")
    return row[0], row[1]


def can_change_member_role(
    actor_role: MembershipRole, current_role: MembershipRole, new_role: MembershipRole
) -> bool:
    """Owners and admins change roles; only an owner can grant or take away the owner role."""
    if not can_manage_organization(actor_role):
        return False
    touches_owner = MembershipRole.OWNER in (current_role, new_role)
    return actor_role is MembershipRole.OWNER or not touches_owner


def can_remove_member(
    actor_role: MembershipRole, target_role: MembershipRole, *, is_self: bool
) -> bool:
    """Everyone can leave; owners and admins remove others, but only an owner removes an owner."""
    if is_self:
        return True
    return can_change_member_role(actor_role, target_role, MembershipRole.MEMBER)


async def _ensure_not_last_owner(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Raise 409 when the organization has a single owner.

    The owner rows are locked, so two owners who demote each other (or leave) at the same
    moment can't both pass this check.
    """
    owners = (
        await session.scalars(
            select(Membership.id)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == MembershipRole.OWNER,
            )
            .with_for_update()
        )
    ).all()
    if len(owners) <= 1:
        raise ConflictError(
            "last_owner", "An organization needs at least one owner; make someone else owner first"
        )


async def change_member_role(
    session: AsyncSession,
    organization: Organization,
    actor: Membership,
    user_id: uuid.UUID,
    role: MembershipRole,
) -> tuple[Membership, User]:
    """Give the member `user_id` another role, on behalf of the member `actor`.

    404 when `user_id` is not a member, 403 when `actor` may not make this change, 409 when it
    would leave the organization without an owner.
    """
    membership, user = await _get_member(session, organization.id, user_id)
    if not can_change_member_role(actor.role, membership.role, role):
        raise ForbiddenError(
            "Only an owner can grant or take away the owner role"
            if can_manage_organization(actor.role)
            else "Only organization owners and admins can change roles"
        )
    if membership.role is MembershipRole.OWNER and role is not MembershipRole.OWNER:
        await _ensure_not_last_owner(session, organization.id)
    membership.role = role
    await session.flush()
    return membership, user


async def remove_member(
    session: AsyncSession, organization: Organization, actor: Membership, user_id: uuid.UUID
) -> None:
    """Remove the member `user_id`, on behalf of the member `actor` (who may be leaving).

    404 when `user_id` is not a member, 403 when `actor` may not remove them, 409 when they
    are the last owner.
    """
    membership, _user = await _get_member(session, organization.id, user_id)
    if not can_remove_member(actor.role, membership.role, is_self=actor.user_id == user_id):
        raise ForbiddenError(
            "Only an owner can remove an owner"
            if can_manage_organization(actor.role)
            else "Only organization owners and admins can remove other members"
        )
    if membership.role is MembershipRole.OWNER:
        await _ensure_not_last_owner(session, organization.id)
    # Their project grants go too: someone who joins again later starts without access.
    await session.execute(
        delete(ProjectGrant).where(
            ProjectGrant.user_id == user_id,
            ProjectGrant.project_id.in_(
                select(Project.id).where(Project.organization_id == organization.id)
            ),
        )
    )
    await session.delete(membership)
    await session.flush()
