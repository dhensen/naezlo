"""The signed-in user and their organizations."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.auth import CurrentUser
from naezlo.db import SessionDep
from naezlo.models import MembershipRole, User
from naezlo.services.organizations import list_user_organizations

router = APIRouter(tags=["me"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None


class MyOrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: MembershipRole


class MeOut(BaseModel):
    user: UserOut
    organizations: list[MyOrganizationOut]


async def build_me(session: AsyncSession, user: User) -> MeOut:
    organizations = await list_user_organizations(session, user.id)
    return MeOut(
        user=UserOut.model_validate(user),
        organizations=[
            MyOrganizationOut(
                id=organization.id, name=organization.name, slug=organization.slug, role=role
            )
            for organization, role in organizations
        ],
    )


@router.get("/me")
async def get_me(user: CurrentUser, session: SessionDep) -> MeOut:
    return await build_me(session, user)
