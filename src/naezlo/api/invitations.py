"""Invitations: invite someone to an organization by email, list and revoke pending ones."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from naezlo.api.deps import OrgAdminContextDep
from naezlo.api.members import MemberOut
from naezlo.db import SessionDep
from naezlo.models import Invitation, InvitationRole, User
from naezlo.services.invitations import invite, list_invitations, revoke_invitation

router = APIRouter(prefix="/orgs/{org_id}/invitations", tags=["invitations"])


class InvitationIn(BaseModel):
    email: EmailStr
    role: InvitationRole = InvitationRole.MEMBER


class InvitedByOut(BaseModel):
    user_id: uuid.UUID
    name: str


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: InvitationRole
    invited_by: InvitedByOut | None
    created_at: datetime


class InviteResultOut(BaseModel):
    """`status` tells which of the two happened: `added` comes with `member`, `invited` with
    `invitation`. `message` says it in words; no email is sent."""

    status: Literal["added", "invited"]
    message: str
    member: MemberOut | None = None
    invitation: InvitationOut | None = None


def _invitation_out(invitation: Invitation, invited_by: User | None) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        invited_by=(
            None
            if invited_by is None
            else InvitedByOut(user_id=invited_by.id, name=invited_by.name)
        ),
        created_at=invitation.created_at,
    )


@router.post("", status_code=201)
async def invite_route(
    body: InvitationIn, org: OrgAdminContextDep, session: SessionDep
) -> InviteResultOut:
    result = await invite(session, org.organization, org.user, body.email, body.role)
    if isinstance(result, Invitation):
        return InviteResultOut(
            status="invited",
            message=(
                f"No email is sent. {result.email} joins {org.organization.name} "
                "the next time they sign in."
            ),
            invitation=_invitation_out(result, org.user),
        )
    membership, user = result
    return InviteResultOut(
        status="added",
        message=f"{user.email} already has an account and is now a member.",
        member=MemberOut(user_id=user.id, email=user.email, name=user.name, role=membership.role),
    )


@router.get("")
async def list_invitations_route(
    org: OrgAdminContextDep, session: SessionDep
) -> list[InvitationOut]:
    invitations = await list_invitations(session, org.organization.id)
    return [_invitation_out(invitation, invited_by) for invitation, invited_by in invitations]


@router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation_route(
    invitation_id: uuid.UUID, org: OrgAdminContextDep, session: SessionDep
) -> None:
    await revoke_invitation(session, org.organization.id, invitation_id)
