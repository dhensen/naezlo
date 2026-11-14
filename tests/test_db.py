"""Database plumbing: migrations, per-test isolation, the session dependency and the mixins."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, String, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from todolist.app import create_app
from todolist.config import Settings
from todolist.db import (
    NAMING_CONVENTION,
    Base,
    SessionDep,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    create_session_factory,
)


class ProbeBase(DeclarativeBase):
    """Separate metadata, so the probe table never shows up in Alembic's autogenerate."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Probe(UUIDPrimaryKeyMixin, TimestampMixin, ProbeBase):
    __tablename__ = "test_probe"

    name: Mapped[str] = mapped_column(String(50), unique=True)


@pytest.fixture(scope="module", autouse=True)
async def probe_table(engine: AsyncEngine) -> AsyncIterator[None]:
    """A committed table that exists for this module only."""
    async with engine.begin() as connection:
        await connection.run_sync(ProbeBase.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(ProbeBase.metadata.drop_all)


async def probe_names(session: AsyncSession) -> list[str]:
    result = await session.execute(text("SELECT name FROM test_probe ORDER BY name"))
    return list(result.scalars())


def test_settings_point_the_app_at_the_test_database(settings: Settings) -> None:
    assert settings.database_url == settings.test_database_url
    assert settings.database_url.endswith("/todolist_test")


async def test_migrations_ran(db_session: AsyncSession) -> None:
    result = await db_session.execute(text("SELECT to_regclass('public.alembic_version')"))

    assert result.scalar_one() == "alembic_version"


# The next two tests run in file order and prove isolation together: the first one
# inserts and even commits a row, the second one must not see it.


async def test_isolation_first_test_inserts_a_row(db_session: AsyncSession) -> None:
    db_session.add(Probe(name="left behind"))
    await db_session.commit()

    assert await probe_names(db_session) == ["left behind"]


async def test_isolation_next_test_does_not_see_it(
    db_session: AsyncSession, engine: AsyncEngine
) -> None:
    assert await probe_names(db_session) == []
    # Nor was it committed for other connections.
    async with engine.connect() as other_connection:
        result = await other_connection.execute(text("SELECT count(*) FROM test_probe"))
        assert result.scalar_one() == 0


def add_probe_routes(app: FastAPI) -> None:
    @app.post("/probe/{name}")
    async def create_probe(name: str, session: SessionDep) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        session.add(Probe(name=name))
        await session.flush()
        if name == "boom":
            raise RuntimeError("boom")
        return {"name": name}


async def test_app_uses_the_test_session(
    app: FastAPI, client: AsyncClient, db_session: AsyncSession
) -> None:
    add_probe_routes(app)

    response = await client.post("/probe/from-the-api")

    assert response.status_code == 200
    assert await probe_names(db_session) == ["from-the-api"]


async def test_get_session_commits_on_success_and_rolls_back_on_error(
    settings: Settings, engine: AsyncEngine
) -> None:
    """The real dependency (no override), against a real engine."""
    app = create_app(settings)
    app.state.session_factory = create_session_factory(engine)
    add_probe_routes(app)
    transport = ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/probe/kept")).status_code == 200
            assert (await client.post("/probe/boom")).status_code == 500

        async with engine.connect() as connection:
            assert await probe_names(AsyncSession(bind=connection)) == ["kept"]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM test_probe"))
        await app.state.engine.dispose()


async def test_mixins_fill_id_and_timestamps(db_session: AsyncSession) -> None:
    probe = Probe(name="mixins")
    db_session.add(probe)
    await db_session.flush()
    await db_session.refresh(probe)

    assert isinstance(probe.id, uuid.UUID)
    assert probe.id.version == 7
    assert isinstance(probe.created_at, datetime)
    assert probe.created_at.tzinfo is not None
    assert probe.updated_at == probe.created_at


def test_constraints_get_conventional_names() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    table = ProbeBase.metadata.tables["test_probe"]
    names = {constraint.name for constraint in table.constraints}

    assert names == {"pk_test_probe", "uq_test_probe_name"}
