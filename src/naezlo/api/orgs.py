"""Organizations: list, create, read and rename."""

from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints

from naezlo.api.deps import OrgAdminContextDep, OrgContext, OrgContextDep
from naezlo.api.me import MyOrganizationOut
from naezlo.auth import CurrentUser
from naezlo.db import SessionDep
from naezlo.models import MembershipRole
from naezlo.services.organizations import (
    create_organization,
    list_user_organizations,
    rename_organization,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])

# organizations.name holds 200 characters.
OrganizationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class OrganizationIn(BaseModel):
    name: OrganizationName


def _organization_out(org: OrgContext) -> MyOrganizationOut:
    return MyOrganizationOut(
        id=org.organization.id,
        name=org.organization.name,
        slug=org.organization.slug,
        role=org.role,
    )


@router.get("")
async def list_organizations(user: CurrentUser, session: SessionDep) -> list[MyOrganizationOut]:
    organizations = await list_user_organizations(session, user.id)
    return [
        MyOrganizationOut(
            id=organization.id, name=organization.name, slug=organization.slug, role=role
        )
        for organization, role in organizations
    ]


@router.post("", status_code=201)
async def create_organization_route(
    body: OrganizationIn, user: CurrentUser, session: SessionDep
) -> MyOrganizationOut:
    organization = await create_organization(session, body.name, user)
    return MyOrganizationOut(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        role=MembershipRole.OWNER,
    )


@router.get("/{org_id}")
async def get_organization(org: OrgContextDep) -> MyOrganizationOut:
    return _organization_out(org)


@router.patch("/{org_id}")
async def rename_organization_route(
    body: OrganizationIn, org: OrgAdminContextDep, session: SessionDep
) -> MyOrganizationOut:
    await rename_organization(session, org.organization, body.name)
    return _organization_out(org)
