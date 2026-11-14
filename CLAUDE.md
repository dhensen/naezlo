# todolist

A multi-tenant todolist app that humans and AI agents share. Features: `README.md`.
Stack, domain model and rules: `DECISIONS.md` (it wins over personal preference).

## Layout

- `src/todolist/`: backend package (`app.py` has the `create_app()` factory, `config.py` the `Settings`)
- `tests/`: pytest tests

## Run

```sh
uv sync
cp .env.example .env   # once
uv run uvicorn todolist.app:create_app --factory --reload
```

Health check: `GET http://localhost:8000/healthz`.

## Quality checks

All of these must pass before a commit:

```sh
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```

`uv run ruff format` and `uv run ruff check --fix` fix most style problems.

## Conventions

- Configuration comes from environment variables through `todolist.config.Settings`
  (pydantic-settings). Every new setting gets a placeholder line in `.env.example`.
  Never commit secret values; `.env` is git-ignored.
- Build the app with `create_app(settings)`; don't create a module-level `app`.
  Tests pass their own `Settings(_env_file=None, ...)` so a local `.env` can't affect them.
- pyright runs in strict mode on `src/` and standard mode on `tests/`.
- Tests are async (`asyncio_mode = "auto"`): write `async def test_...` and use the
  `client` fixture (httpx `AsyncClient` on the ASGI app) from `tests/conftest.py`.
- The product name lives in `Settings.app_name` only.
