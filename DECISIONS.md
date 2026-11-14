# Decisions

Decisions that `README.md` does not cover. Append new ones at the bottom with a date and the story ID.

## Stack (2026-11-14, before US-001)

- **Backend** lives at the repo root: Python 3.14, uv, FastAPI, SQLAlchemy 2 (async) with asyncpg, Alembic, pydantic-settings, Authlib for Google login, the official `mcp` Python SDK for the MCP server. Package in `src/todolist/`.
- **Database**: PostgreSQL 18 through `docker compose`. Tests run against a real Postgres test database, each test inside a transaction that is rolled back. No SQLite.
- **Frontend** lives in `frontend/`: Vite, React, TypeScript (strict), React Router, TanStack Query, Tailwind CSS. API types are generated from FastAPI's OpenAPI schema. Package manager is npm (pnpm is not installed on this machine).
- **Serving**: in development Vite proxies to the backend; in production FastAPI serves `frontend/dist`.
- **Quality checks**
  - Backend: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, `uv run pytest`
  - Frontend (once `frontend/` exists, US-027): `npm --prefix frontend run lint`, `npm --prefix frontend run typecheck`, `npm --prefix frontend run test`
  - End to end (once US-029 exists): `npm --prefix frontend run e2e`
- **Login without Google credentials**: the loop has no Google OAuth client. Google is mocked in tests. A dev-login endpoint, enabled only when `DEV_LOGIN=true`, is used for local runs and end-to-end tests. It must be off by default.
- **Secrets** come from environment variables. `.env` is git-ignored; `.env.example` documents every variable with safe placeholder values.

## Domain (2026-11-14, before US-001)

- **Tenancy**: `User`, `Organization`, `Membership` with role `owner | admin | member`. A new user gets a default organization on first sign-in. Invitations are by email and are accepted automatically on the invitee's next sign-in; v1 sends no email.
- **Agents**: an `Agent` belongs to one organization and is a principal like a user. Code that checks permissions or records audit events takes a `Principal` (kind `user | agent`), never a bare user.
- **Hierarchy**: `Organization` → `Project` → `TodoList` → `Item`. An item has a title, notes, status `open | done` and a position.
- **ACL**
  - Grants exist on projects and on lists, for a user or an agent, with role `viewer | editor | admin`. List grants also allow `none`.
  - Effective role on a list: the list grant if there is one, otherwise the project grant.
  - Organization owners and admins are admin on everything in their organization.
  - No role means the resource does not exist for that principal: respond 404, not 403. Use 403 when the principal can see the resource but the action needs a higher role.
- **List mode**: `human_only | ai_only | mixed`.
  - Default for a new list: `mixed` when the organization has at least one agent, otherwise `human_only`.
  - `human_only`: agents have no access, whatever their grants.
  - `ai_only`: humans can read according to their role but cannot change items. List admins can still rename the list, change its mode and manage its grants.
  - `mixed`: both act according to their role.
- **Audit log**: one `audit_events` table with organization, project, list (nullable), actor kind, actor id, actor name snapshot, action, target and JSON details. Events are written in the same transaction as the change and survive deletion of their target.
- **MCP**: streamable HTTP at `/mcp`. The app is its own OAuth 2.1 authorization server (metadata discovery, dynamic client registration, PKCE with S256, refresh token rotation, revocation). On the consent screen the signed-in user picks which agent the client acts as; that requires being owner or admin of the agent's organization. Tokens are stored hashed and resolve to that agent. MCP tools and the HTTP API share the same service functions.
- **Not in v1**: billing, sending email, password login. The product name ("needs a better name" in the README) is a human decision; keep `todolist` as the working name and keep it in one place per layer (a setting in the backend, a constant in the frontend).

## Database plumbing (2026-11-14, US-002)

- **Host port 5435** for the compose Postgres (override with `POSTGRES_PORT`; then also set `DATABASE_URL` and `TEST_DATABASE_URL`). Ports 5432 to 5434 are used by other projects on the development machine. The compose credentials (`todolist` / `todolist`) are local-only defaults, not secrets.
- **Primary keys** are UUIDv7 generated in Python (`uuid.uuid7`), so ids are known before the flush and sort by creation time.
- **Timestamps** are `timestamptz`, set by the database (`now()`).
- **One transaction per request**: `get_session` commits when the handler returns and rolls back when it raises. Routes use `SessionDep`, which has `scope="function"` so the commit happens before the response is sent. Services flush; they don't commit.
- **Alembic** lives in `migrations/` with an async `env.py`. The URL comes from `Settings.database_url`; nothing is stored in `alembic.ini`. New revision files are formatted and lint-fixed by ruff through post-write hooks.
- **Test database**: the test session drops and recreates the `public` schema of `todolist_test` and migrates it to head, so every run also proves that migrations work on an empty database. The app under test gets `database_url = test_database_url`.

## Tenancy models (2026-11-14, US-003)

- **Emails** are stored trimmed and lowercased. The `User` model normalizes on assignment and a check constraint (`email = lower(email)`) guards the column, so the plain unique constraint is case-insensitive in effect. Look users up with `normalize_email(...)`.
- **Enums** are native PostgreSQL enum types that store the lowercase values (`owner`, not `OWNER`), built with `todolist.db.value_enum`. Python side: `enum.StrEnum`.
- **Deleting a user** deletes their memberships (`ON DELETE CASCADE`), like deleting an organization does. v1 has no user deletion feature; this only keeps the schema consistent.
- **Relationships** are declared with `lazy="raise"`: async code cannot lazy-load, so a forgotten `selectinload` fails loudly instead of with `MissingGreenlet`.

## Sessions and sign-in (2026-11-14, US-004)

- **Session**: Starlette `SessionMiddleware`, a signed cookie named `session` that holds only the user id (14 days, HttpOnly, SameSite=Lax). It is `Secure` when `ENVIRONMENT=production`; development and tests run on plain http.
- **`SESSION_SECRET`** has an insecure development default so a fresh checkout runs. With `ENVIRONMENT=production` the app refuses to start when the secret is unset, and also when `DEV_LOGIN=true`: dev-login signs in as any email address without a password.
- **Dev-login when disabled** answers 404 to every request, before the body is validated, like a route that does not exist. The route stays in the OpenAPI schema so the generated frontend types do not depend on the environment.
- **Error body**: `{"detail": "<message>", "code": "<snake_case>"}`. Raise a `todolist.errors.AppError` (or a subclass); clients branch on `code`. FastAPI's own errors (422 validation, unknown route) have `detail` only.
- **Default organization**: named "<name>'s organization", slug derived from the user's name ("Ada Lovelace" → `ada-lovelace`). Slugs are ASCII `[a-z0-9-]`; a taken slug gets a number (`ada-2`, `ada-3`), and a name without usable characters becomes `org`.
- **`get_or_create_user`** finds a user by `google_sub` when one is given, otherwise by email. An existing user keeps their stored name and email; a missing `google_sub` is filled in. Only creation makes a default organization.
- **`/api/me` and dev-login** return `{"user": {...}, "organizations": [{id, name, slug, role}]}`, organizations in the order the user joined them.
- **Correction to "Primary keys" above**: the UUIDv7 default is applied by SQLAlchemy at flush time, so `obj.id` is `None` until the first flush. Link new objects through relationships (`Membership(organization=org, ...)`) or flush first.
