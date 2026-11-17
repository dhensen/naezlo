"""User, Organization and Membership: creation, constraints and cascades."""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from naezlo.models import Membership, MembershipRole, Organization, User, normalize_email


async def make_user(session: AsyncSession, email: str = "ada@example.com") -> User:
    user = User(email=email, name="Ada")
    session.add(user)
    await session.flush()
    return user


async def make_organization(session: AsyncSession, slug: str = "ada") -> Organization:
    organization = Organization(name="Ada's organization", slug=slug)
    session.add(organization)
    await session.flush()
    return organization


async def expect_integrity_error(session: AsyncSession, constraint: str) -> None:
    """Flush inside a savepoint, so the session stays usable after the expected failure."""
    with pytest.raises(IntegrityError) as error:
        async with session.begin_nested():
            await session.flush()
    assert constraint in str(error.value)


async def test_create_user_with_organization_and_membership(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)
    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    await db_session.flush()
    db_session.expunge_all()

    loaded = (
        await db_session.execute(
            select(Membership)
            .where(Membership.user_id == user.id)
            .options(selectinload(Membership.user), selectinload(Membership.organization))
        )
    ).scalar_one()

    assert loaded.role is MembershipRole.OWNER
    assert loaded.user.email == "ada@example.com"
    assert loaded.user.avatar_url is None
    assert loaded.user.google_sub is None
    assert loaded.user.created_at is not None
    assert loaded.organization.name == "Ada's organization"
    assert loaded.organization.slug == "ada"


async def test_membership_can_be_added_through_the_organization(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = Organization(name="Team", slug="team")
    organization.memberships.append(Membership(user_id=user.id, role=MembershipRole.MEMBER))
    db_session.add(organization)
    await db_session.flush()

    count = await db_session.scalar(
        select(func.count()).select_from(Membership).where(Membership.user_id == user.id)
    )
    assert count == 1


async def test_role_is_stored_as_its_lowercase_value(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)
    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN)
    )
    await db_session.flush()

    stored = await db_session.scalar(text("SELECT role::text FROM memberships"))
    assert stored == "admin"


async def test_email_is_stored_lowercased(db_session: AsyncSession) -> None:
    user = await make_user(db_session, email="  Ada.Lovelace@Example.COM ")

    assert user.email == "ada.lovelace@example.com"
    assert normalize_email("Ada.Lovelace@Example.COM") == user.email
    stored = await db_session.scalar(text("SELECT email FROM users"))
    assert stored == "ada.lovelace@example.com"


async def test_database_rejects_an_email_that_is_not_lowercase(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO users (id, email, name) "
                    "VALUES (gen_random_uuid(), 'Ada@Example.com', 'Ada')"
                )
            )


async def test_email_is_unique_regardless_of_case(db_session: AsyncSession) -> None:
    await make_user(db_session, email="ada@example.com")
    db_session.add(User(email="ADA@example.com", name="Other Ada"))

    await expect_integrity_error(db_session, "uq_users_email")


async def test_google_sub_is_unique_but_may_be_missing(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            User(email="a@example.com", name="A"),
            User(email="b@example.com", name="B"),
            User(email="c@example.com", name="C", google_sub="sub-1"),
        ]
    )
    await db_session.flush()  # two users without google_sub are fine

    db_session.add(User(email="d@example.com", name="D", google_sub="sub-1"))
    await expect_integrity_error(db_session, "uq_users_google_sub")


async def test_organization_slug_is_unique(db_session: AsyncSession) -> None:
    await make_organization(db_session, slug="acme")
    db_session.add(Organization(name="Another Acme", slug="acme"))

    await expect_integrity_error(db_session, "uq_organizations_slug")


async def test_a_user_has_one_membership_per_organization(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)
    other_organization = await make_organization(db_session, slug="other")
    db_session.add_all(
        [
            Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.OWNER),
            Membership(
                organization_id=other_organization.id, user_id=user.id, role=MembershipRole.MEMBER
            ),
        ]
    )
    await db_session.flush()  # the same user in two organizations is fine

    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.MEMBER)
    )
    await expect_integrity_error(db_session, "uq_memberships_organization_id_user_id")


async def test_database_rejects_an_unknown_role(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)

    with pytest.raises(Exception, match="membership_role"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (gen_random_uuid(), :organization_id, :user_id, 'superuser')"
                ),
                {"organization_id": organization.id, "user_id": user.id},
            )


async def test_deleting_an_organization_deletes_its_memberships(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)
    kept_organization = await make_organization(db_session, slug="kept")
    db_session.add_all(
        [
            Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.OWNER),
            Membership(
                organization_id=kept_organization.id, user_id=user.id, role=MembershipRole.OWNER
            ),
        ]
    )
    await db_session.flush()

    # Raw SQL, so this proves the database cascade and not the ORM one.
    await db_session.execute(
        text("DELETE FROM organizations WHERE id = :id"), {"id": organization.id}
    )

    remaining = (await db_session.execute(text("SELECT organization_id FROM memberships"))).all()
    assert [row.organization_id for row in remaining] == [kept_organization.id]
    assert await db_session.scalar(text("SELECT count(*) FROM users")) == 1


async def test_deleting_an_organization_through_the_orm(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    organization = await make_organization(db_session)
    db_session.add(
        Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    await db_session.flush()

    await db_session.delete(organization)
    await db_session.flush()

    assert await db_session.scalar(select(func.count()).select_from(Membership)) == 0
