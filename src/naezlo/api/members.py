"""Organization members: list, change a role, remove (or leave)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from naezlo.api.deps import OrgAdminContextDep, OrgContextDep
from naezlo.db import SessionDep
from naezlo.models import Membership, MembershipRole, User
from naezlo.services.organizations import change_member_role, list_members, remove_member

router = APIRouter(prefix="/orgs/{org_id}/members", tags=["members"])


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: MembershipRole


class MemberRoleIn(BaseModel):
    role: MembershipRole


def _member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=membership.role)


@router.get("")
async def list_members_route(org: OrgContextDep, session: SessionDep) -> list[MemberOut]:
    members = await list_members(session, org.organization.id)
    return [_member_out(membership, user) for membership, user in members]


@router.patch("/{user_id}")
async def change_member_role_route(
    user_id: uuid.UUID, body: MemberRoleIn, org: OrgAdminContextDep, session: SessionDep
) -> MemberOut:
    membership, user = await change_member_role(
        session, org.organization, org.membership, user_id, body.role
    )
    return _member_out(membership, user)


@router.delete("/{user_id}", status_code=204)
async def remove_member_route(user_id: uuid.UUID, org: OrgContextDep, session: SessionDep) -> None:
    # Not the admin dependency: a plain member may remove themselves. The service decides.
    await remove_member(session, org.organization, org.membership, user_id)
