import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from todolist.app import create_app
from todolist.config import Settings
from todolist.db import get_session

REPO_ROOT = Path(__file__).resolve().parent.parent


def _test_settings() -> Settings:
    # _env_file=None keeps a developer's local .env out of the tests.
    # dev_login is on because tests sign in through it (tests/helpers.py); the default is off.
    base = Settings(_env_file=None, environment="test", dev_login=True)  # pyright: ignore[reportCallIssue]
    # The app under test must never reach the development database.
    return base.model_copy(update={"database_url": base.test_database_url})


@pytest.fixture
def settings() -> Settings:
    return _test_settings()


async def _reset_schema(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest.fixture(scope="session")
def migrated_database_url() -> str:
    """Empty the test database and migrate it to head, once per test session.

    This is a sync fixture on purpose: Alembic's env.py calls `asyncio.run()`, which
    cannot run inside the event loop that async fixtures use.
    """
    database_url = _test_settings().database_url
    asyncio.run(_reset_schema(database_url))
    config = Config(REPO_ROOT / "alembic.ini")
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    command.upgrade(config, "head")
    return database_url


@pytest.fixture(scope="session")
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back after the test.

    The app uses this same session (see `app`), so a test can prepare rows, call the API
    and inspect the result. `session.commit()` only releases a savepoint; nothing reaches
    other tests.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def app(settings: Settings, db_session: AsyncSession) -> Iterator[FastAPI]:
    app = create_app(settings)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    yield app
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
