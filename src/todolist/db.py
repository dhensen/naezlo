"""Database plumbing: declarative base, shared mixins, engine, sessions.

Models subclass `Base` and are imported in `todolist.models` so that Alembic sees them.
"""

import enum
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import DateTime, Enum, MetaData, Uuid, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names, so Alembic can address them in later migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key, generated in Python so the id is known before the flush."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)


class TimestampMixin:
    """`created_at` and `updated_at`, both set by the database."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def _enum_values(enum_class: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_class]


def value_enum(enum_class: type[enum.Enum], name: str) -> Enum:
    """A PostgreSQL enum column type that stores the members' values ("owner"), not their names.

    `name` is the name of the database type. Autogenerate does not drop it in `downgrade()`;
    add `sa.Enum(name=...).drop(op.get_bind())` to the migration by hand.
    """
    return Enum(enum_class, name=name, values_callable=_enum_values)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after the commit, which async code
    # needs because it cannot lazy-load on attribute access.
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """A session with one transaction: committed when the block ends, rolled back when it raises."""
    async with session_factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        else:
            await session.commit()


# Opens a session with its transaction, for code that runs outside a FastAPI route (the MCP
# server): `async with session_scope() as session`. The app's one is `app.state.session_scope`.
SessionScope = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session and one transaction per request: commit on success, roll back on error."""
    async with transaction(request.app.state.session_factory) as session:
        yield session


# Use this in route signatures: `session: SessionDep`.
# scope="function" ends the dependency (and so commits) before the response is sent, so a
# client never sees a success response for a change that failed to commit.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
