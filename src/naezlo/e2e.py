"""The backend for the browser tests: `python -m naezlo.e2e --port 8765`.

`npm --prefix frontend run e2e` builds the frontend and lets Playwright start this module
(`frontend/playwright.config.ts`). It empties the dedicated end-to-end database
(`Settings.e2e_database_url`, created when it does not exist yet), migrates it to head and
serves the app with dev-login on and the built frontend. Run it from the repository root.
"""

import argparse
import asyncio
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from naezlo.app import create_app
from naezlo.config import Settings

# Only a database with this ending is ever emptied, whatever E2E_DATABASE_URL says.
E2E_DATABASE_SUFFIX = "_e2e"


def e2e_settings(port: int) -> Settings:
    """The app's settings for a browser test run. A local `.env` has no say in them."""
    base = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        environment="test",
        dev_login=True,
        public_base_url=f"http://localhost:{port}",
        google_client_id=None,
        google_client_secret=None,
    )
    return base.model_copy(update={"database_url": base.e2e_database_url})


async def _ensure_database(database_url: str) -> None:
    """Create the database when the server does not have it (an older Docker volume)."""
    url = make_url(database_url)
    name = url.database
    if name is None or not name.endswith(E2E_DATABASE_SUFFIX):
        raise SystemExit(
            f"Refusing to empty the database {name!r}: the end-to-end database must have a "
            f"name that ends with {E2E_DATABASE_SUFFIX!r} (E2E_DATABASE_URL)."
        )
    # CREATE DATABASE cannot run in a transaction; `postgres` is the maintenance database.
    engine = create_async_engine(
        url.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    async with engine.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        )
        if not exists:
            quoted = name.replace('"', '""')
            await connection.execute(text(f'CREATE DATABASE "{quoted}"'))
    await engine.dispose()


async def _empty_database(database_url: str) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


def prepare_database(database_url: str) -> None:
    """An empty database at the newest migration."""
    asyncio.run(_ensure_database(database_url))
    asyncio.run(_empty_database(database_url))
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    # Alembic's env.py runs its own event loop, so this is called outside of one.
    command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    port: int = parser.parse_args().port

    settings = e2e_settings(port)
    if not Path("alembic.ini").is_file():
        raise SystemExit("Run this from the repository root (alembic.ini was not found).")
    dist = settings.frontend_dist
    if dist is None or not (dist / "index.html").is_file():
        raise SystemExit(f"No frontend build in {dist}: run `npm --prefix frontend run build`.")

    prepare_database(settings.database_url)
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
