"""Invitations: invite someone to an organization by email, list, resend and revoke pending ones."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from naezlo.api.deps import OrgAdminContextDep
from naezlo.api.members import MemberOut
from naezlo.config import SettingsDep
from naezlo.db import SessionDep
from naezlo.errors import AppError
from naezlo.mailer import MailerDep
from naezlo.models import Invitation, InvitationRole, User
from naezlo.services.invitation_mails import added_mail, invitation_mail, try_send
from naezlo.services.invitations import (
    get_invitation,
    invite,
    list_invitations,
    revoke_invitation,
)

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
    `invitation`. `email_sent` tells whether the person was emailed about it (never when
    email is not configured); `message` says all of it in words."""

    status: Literal["added", "invited"]
    message: str
    email_sent: bool
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
    body: InvitationIn,
    org: OrgAdminContextDep,
    session: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
) -> InviteResultOut:
    organization = org.organization
    result = await invite(session, organization, org.user, body.email, body.role)
    # The mail goes out after the change is flushed. When it fails the change stands, and
    # the message says so: an invitation works without its email.
    if isinstance(result, Invitation):
        joins = f"{result.email} joins {organization.name} the next time they sign in."
        mail = invitation_mail(settings, organization, org.user, result.email, result.role)
        sent = await try_send(mailer, mail)
        if sent:
            message = f"An invitation was emailed to {result.email}. They join when they sign in."
        elif mailer is None:
            message = f"No email is sent. {joins}"
        else:
            message = f'The email could not be sent; use "Resend" to try again. {joins}'
        return InviteResultOut(
            status="invited",
            message=message,
            email_sent=sent,
            invitation=_invitation_out(result, org.user),
        )
    membership, user = result
    sent = await try_send(
        mailer, added_mail(settings, organization, org.user, user, membership.role)
    )
    message = f"{user.email} already has an account and is now a member."
    return InviteResultOut(
        status="added",
        message=f"{message} They were told by email." if sent else message,
        email_sent=sent,
        member=MemberOut(user_id=user.id, email=user.email, name=user.name, role=membership.role),
    )


@router.get("")
async def list_invitations_route(
    org: OrgAdminContextDep, session: SessionDep
) -> list[InvitationOut]:
    invitations = await list_invitations(session, org.organization.id)
    return [_invitation_out(invitation, invited_by) for invitation, invited_by in invitations]


@router.post("/{invitation_id}/send", status_code=204)
async def resend_invitation_route(
    invitation_id: uuid.UUID,
    org: OrgAdminContextDep,
    session: SessionDep,
    settings: SettingsDep,
    mailer: MailerDep,
) -> None:
    """Email a pending invitation again, in the name of whoever asks for it."""
    invitation = await get_invitation(session, org.organization.id, invitation_id)
    if mailer is None:
        raise AppError(409, "email_not_configured", "This server does not send email.")
    mail = invitation_mail(settings, org.organization, org.user, invitation.email, invitation.role)
    if not await try_send(mailer, mail):
        raise AppError(502, "email_failed", "The email could not be sent. Try again later.")


@router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation_route(
    invitation_id: uuid.UUID, org: OrgAdminContextDep, session: SessionDep
) -> None:
    await revoke_invitation(session, org.organization.id, invitation_id)
