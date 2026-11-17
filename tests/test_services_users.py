"""get_or_create_user, the default organization and slugs."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from naezlo.models import Membership, MembershipRole, Organization, User
from naezlo.services.organizations import (
    SLUG_LOCK_KEY,
    create_organization,
    list_user_organizations,
    slugify,
    unique_slug,
)
from naezlo.services.users import get_or_create_user


async def organizations_of(session: AsyncSession, user: User) -> list[Organization]:
    return [organization for organization, _ in await list_user_organizations(session, user.id)]


async def test_new_user_gets_a_default_organization_as_owner(db_session: AsyncSession) -> None:
    user = await get_or_create_user(db_session, "Ada@Example.com", "Ada")

    assert user.email == "ada@example.com"
    assert user.google_sub is None
    assert [
        (o.name, o.slug, role) for o, role in await list_user_organizations(db_session, user.id)
    ] == [("Ada's organization", "ada", MembershipRole.OWNER)]


async def test_existing_user_is_returned_without_a_new_organization(
    db_session: AsyncSession,
) -> None:
    first = await get_or_create_user(db_session, "ada@example.com", "Ada")

    second = await get_or_create_user(db_session, "ADA@example.com ", "Renamed")

    assert second.id == first.id
    assert second.name == "Ada"
    assert len(await organizations_of(db_session, first)) == 1
    assert len((await db_session.scalars(select(Membership))).all()) == 1


async def test_users_with_the_same_name_get_different_slugs(db_session: AsyncSession) -> None:
    users = [
        await get_or_create_user(db_session, f"ada{number}@example.com", "Ada")
        for number in range(3)
    ]

    slugs = [(await organizations_of(db_session, user))[0].slug for user in users]

    assert slugs == ["ada", "ada-2", "ada-3"]


async def test_google_sub_is_stored_and_used_for_lookup(db_session: AsyncSession) -> None:
    created = await get_or_create_user(db_session, "ada@example.com", "Ada", google_sub="g-1")

    # Found by google_sub even though the email address changed at Google.
    found = await get_or_create_user(db_session, "ada@new.example.com", "Ada", google_sub="g-1")

    assert created.google_sub == "g-1"
    assert found.id == created.id
    assert found.email == "ada@example.com"


async def test_existing_user_without_google_sub_is_linked(db_session: AsyncSession) -> None:
    created = await get_or_create_user(db_session, "ada@example.com", "Ada")

    linked = await get_or_create_user(db_session, "ada@example.com", "Ada", google_sub="g-1")

    assert linked.id == created.id
    assert linked.google_sub == "g-1"
    assert len(await organizations_of(db_session, linked)) == 1


async def test_a_very_long_name_still_fits(db_session: AsyncSession) -> None:
    user = await get_or_create_user(db_session, "long@example.com", "x" * 200)

    organization = (await organizations_of(db_session, user))[0]
    assert len(organization.name) == 200
    assert organization.name.endswith("'s organization")
    assert len(organization.slug) <= 100


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ada Lovelace", "ada-lovelace"),
        ("  Zoë's   Team!  ", "zoe-s-team"),
        ("ACME, Inc.", "acme-inc"),
        ("日本語", "org"),
        ("---", "org"),
        ("a" * 120, "a" * 80),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


async def test_picking_a_slug_locks_out_other_transactions(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    # Two people with the same name signing up at once: the second waits for the first to
    # commit instead of picking the same slug.
    try_lock = select(func.pg_try_advisory_xact_lock(SLUG_LOCK_KEY))
    async with engine.connect() as other:
        assert await other.scalar(try_lock) is True
        await other.rollback()

        await unique_slug(db_session, "Ada")

        assert await other.scalar(try_lock) is False


async def test_unique_slug_skips_taken_slugs(db_session: AsyncSession) -> None:
    owner = await get_or_create_user(db_session, "ada@example.com", "Ada")
    await create_organization(db_session, "Team", owner)
    await create_organization(db_session, "Team", owner)
    # "team-building" starts with "team-" but must not count as a numbered "team".
    await create_organization(db_session, "Team building", owner)

    assert await unique_slug(db_session, "Team") == "team-3"
    assert await unique_slug(db_session, "Team building") == "team-building-2"
    assert await unique_slug(db_session, "Other") == "other"
    assert [o.slug for o in await organizations_of(db_session, owner)] == [
        "ada",
        "team",
        "team-2",
        "team-building",
    ]
