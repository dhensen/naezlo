"""Invitations: invite an email address to an organization, list, revoke, accept on sign-in.

No email is sent in v1. Someone who already has an account becomes a member right away;
anyone else gets a pending invitation that turns into a membership on their next sign-in.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from todolist.errors import ConflictError, NotFoundError
from todolist.models import (
    Invitation,
    InvitationRole,
    Membership,
    MembershipRole,
    Organization,
    User,
    normalize_email,
)


def membership_role(role: InvitationRole) -> MembershipRole:
    return MembershipRole(role.value)


async def invite(
    session: AsyncSession,
    organization: Organization,
    invited_by: User,
    email: str,
    role: InvitationRole,
) -> tuple[Membership, User] | Invitation:
    """Invite `email` to the organization with `role`.

    Returns the new membership and its user when the email belongs to an existing user (they
    are a member from now on), otherwise the stored invitation. 409 `already_member` when that
    user is a member already, 409 `already_invited` when the email has a pending invitation.

    The caller checks that `invited_by` may manage the organization.
    """
    email = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == email))
    if user is not None:
        existing = await session.scalar(
            select(Membership.id).where(
                Membership.organization_id == organization.id, Membership.user_id == user.id
            )
        )
        if existing is not None:
            raise ConflictError("already_member", f"{email} is already a member")
        membership = Membership(
            organization_id=organization.id, user_id=user.id, role=membership_role(role)
        )
        session.add(membership)
        await session.flush()
        return membership, user

    pending = await session.scalar(
        select(Invitation.id).where(
            Invitation.organization_id == organization.id, Invitation.email == email
        )
    )
    if pending is not None:
        raise ConflictError("already_invited", f"{email} has already been invited")
    invitation = Invitation(
        organization_id=organization.id, email=email, role=role, invited_by=invited_by.id
    )
    session.add(invitation)
    await session.flush()
    return invitation


async def list_invitations(
    session: AsyncSession, organization_id: uuid.UUID
) -> list[tuple[Invitation, User | None]]:
    """The pending invitations of an organization with the user who sent each, oldest first."""
    rows = await session.execute(
        select(Invitation, User)
        .outerjoin(User, User.id == Invitation.invited_by)
        .where(Invitation.organization_id == organization_id)
        .order_by(Invitation.id)
    )
    return [(invitation, user) for invitation, user in rows]


async def revoke_invitation(
    session: AsyncSession, organization_id: uuid.UUID, invitation_id: uuid.UUID
) -> None:
    """Delete a pending invitation; 404 when the organization has no such invitation."""
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id, Invitation.organization_id == organization_id
        )
    )
    if invitation is None:
        raise NotFoundError("Invitation not found")
    await session.delete(invitation)
    await session.flush()


async def accept_pending_invitations(session: AsyncSession, user: User) -> None:
    """Turn every pending invitation for the user's email into a membership.

    Called on sign-in. An invitation to an organization the user is in already is just removed.
    """
    invitations = (
        await session.scalars(
            select(Invitation).where(Invitation.email == user.email).order_by(Invitation.id)
        )
    ).all()
    if not invitations:
        return
    member_of = set(
        await session.scalars(
            select(Membership.organization_id).where(Membership.user_id == user.id)
        )
    )
    for invitation in invitations:
        if invitation.organization_id not in member_of:
            session.add(
                Membership(
                    organization_id=invitation.organization_id,
                    user_id=user.id,
                    role=membership_role(invitation.role),
                )
            )
        await session.delete(invitation)
    await session.flush()
