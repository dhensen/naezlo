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

## Google login (2026-11-14, US-005)

- **Client**: Authlib's Starlette OpenID Connect client behind `todolist.google.GoogleClient` (Authlib has no type information). Endpoints and signing keys come from Google's discovery document; the flow uses state, nonce and PKCE (S256), all kept in the session cookie. Scope: `openid email profile`.
- **HTTP library**: `httpx2` is a runtime dependency because Authlib 1.9 uses it and deprecates plain `httpx`. `httpx` stays a dev dependency for the test client.
- **`PUBLIC_BASE_URL`** (default `http://localhost:8000`) is the URL people open in their browser. The Google redirect URI is `<PUBLIC_BASE_URL>/api/auth/google/callback`, never derived from the Host header. US-020 uses the same setting for the OAuth issuer.
- **Failures redirect, they don't return JSON**: both Google routes are opened by browser navigation, so a failed sign-in goes to `/login?error=<code>` with code `google_login_failed` (bad or reused state, refusal at Google, invalid ID token), `email_not_verified`, `google_account_conflict` or `google_unavailable`. The login page (US-028) should show a message for these. When Google login is not configured both routes answer a JSON 404 like any unknown route.
- **`next`** must start with a single `/` and contain no backslash or control character; anything else is ignored and the user lands on `/`. It lives in the session under `login_next` and is forgotten when a new login starts without it.
- **Email linked to another Google account**: when the ID token's `sub` is unknown but its email belongs to a user who already has a different `google_sub`, the sign-in is refused (`google_account_conflict`). The address was probably reassigned; signing in would hand over someone else's account.
- **Profile data**: a returning user keeps their stored name and email even when Google reports new ones (found by `sub`). The picture is refreshed on every Google sign-in. `email_verified` must be the JSON value `true`.

## Organization API (2026-11-14, US-006)

- **Shape**: every organization endpoint returns `{id, name, slug, role}`, where `role` is the caller's own role (the same object as in `/api/me`). `POST /api/orgs` answers 201.
- **Names** are trimmed and must be 1 to 200 characters (422 otherwise). Names need not be unique; slugs are.
- **Renaming keeps the slug**, so links that contain it keep working. v1 has no way to change a slug.
- **Not a member means 404**, with the same body as an id that does not exist. A member whose role is too low gets 403 with code `forbidden` (`ForbiddenError`).
- **Organization-level role checks** live in one place: `can_manage_organization(role)` in `services/organizations.py`, applied by the `OrgAdminContextDep` dependency. Routes don't compare roles themselves. The permission service of US-011 (projects and lists, with a `Principal`) should build on this function rather than repeat the rule.

## Organization members (2026-11-14, US-007)

- **Shape**: a member is `{user_id, email, name, role}`, listed in the order people joined. `PATCH` returns the changed member, `DELETE` answers 204. The path id is the user's id, not the membership's.
- **Who may change what**: owners and admins change roles and remove members. Any change that involves the owner role (granting it, demoting an owner, removing an owner) needs an owner; an admin gets 403. Admins can demote and remove other admins. Everyone can remove themselves (leave).
- **Last owner**: demoting or removing the only owner answers 409 with code `last_owner`, also when that owner is the only member. An owner who wants out makes someone else owner first. The owner rows are locked (`FOR UPDATE`) during the check, so two owners can't leave at the same moment.
- **Order of answers**: not a member of the organization → 404; target is not a member → 404 `Member not found`; not allowed → 403; last owner → 409. A member (not owner or admin) who patches gets 403 before the target is looked up.
- **Rules live in the service**: `can_change_member_role` and `can_remove_member` in `services/organizations.py`; `change_member_role` and `remove_member` apply them and raise the `AppError`s themselves, because whether a removal is allowed depends on the target and can't be a route dependency. Conflicts use `ConflictError(code, detail)` with a specific code.

## Invitations (2026-11-14, US-008)

- **Table**: `invitations` with `organization_id`, `email` (trimmed and lowercased, same check constraint as `users.email`), `role`, `invited_by` and the usual timestamps; unique on `(organization_id, email)`. `role` is its own enum type `invitation_role` (`admin | member`): ownership is never given by invitation, so `owner` is a 422. Deleting the organization deletes its invitations; deleting the inviter keeps them (`invited_by` becomes null).
- **Who**: inviting, listing and revoking all need an owner or admin (`OrgAdminContextDep`); a member gets 403. Admins may invite admins, as they may promote members to admin.
- **`POST /api/orgs/{org_id}/invitations`** answers 201 with `{status, message, member, invitation}`. `status` is `added` (the email has an account: `member` is the new member, no invitation is stored) or `invited` (`invitation` is the stored one). `message` says in words what happened, including that no email is sent and the person joins on their next sign-in. `role` defaults to `member`.
- **Conflicts**: the email is a member already → 409 `already_member`; it has a pending invitation in this organization → 409 `already_invited` (revoke and invite again to change the role).
- **Invitation shape**: `{id, email, role, invited_by: {user_id, name} | null, created_at}`, listed oldest first. `DELETE` answers 204, and 404 for an id that is not a pending invitation of this organization.
- **Acceptance**: `get_or_create_user` turns every pending invitation for the user's stored email into a membership on every sign-in, for new users after their default organization is created (so that one stays first) and for existing users too. An invitation to an organization the user is already in is dropped without changing their role. There is no accept or decline step in v1.

## Agents and the Principal type (2026-11-14, US-009)

- **`Principal`** (`todolist.principals`) is the actor type for permission checks and audit events: a frozen dataclass with `kind` (`PrincipalKind`: `user | agent`), `id` (the user's or the agent's id), `organization_id` (the organization the actor acts in) and `name` (the display name at that moment, for the audit log's actor name snapshot). Build one with `Principal.for_user(user, organization_id)` or `Principal.for_agent(agent)`; in an org-scoped route `org.principal` gives the caller's. An agent's organization is the one it belongs to; a user's is the one the request is about. Building a principal checks nothing: the caller has established membership. The permission service (US-011) and audit recording (US-018) take a `Principal`, never a bare `User` or `Agent`.
- **Managing agents is an organization-level rule**, like members and invitations: listing needs any membership (`OrgContextDep`), creating, changing and deleting need an owner or admin (`OrgAdminContextDep`, built on `can_manage_organization`). Only users manage agents in v1, so these routes don't take a `Principal` yet.
- **Table**: `agents` with `organization_id` (cascade), `name` (200), `description` (text, nullable), `created_by` (the user; becomes null when that user is deleted) and timestamps; unique on `(organization_id, name)`.
- **Names** are trimmed, 1 to 200 characters, and unique per organization by exact match (`Claude` and `claude` are two names). A taken name answers 409 `agent_name_taken`. The unique constraint decides (insert or update inside a savepoint), not a query beforehand.
- **Descriptions** are trimmed, at most 2000 characters; an empty one is stored as null.
- **Shape**: `{id, name, description, created_by, created_at, updated_at}`, `created_by` being a user id or null; listed oldest first. `POST` answers 201, `DELETE` 204. `PATCH` changes only the fields that are sent: `description: null` clears it, `name: null` is a 422. There is no `GET` for a single agent (no story needs one yet).
- **Order of answers**: not a member → 404 `Organization not found`; member but not owner or admin → 403 (also for an agent id that does not exist); unknown agent or one of another organization → 404 `Agent not found`.

## Projects (2026-11-14, US-010)

- **Table**: `projects` with `organization_id` (cascade, indexed), `name` (200), `description` (text, nullable), `created_by` (the user; becomes null when that user is deleted) and timestamps.
- **Names** are trimmed, 1 to 200 characters, and need not be unique: two projects in one organization can have the same name. Descriptions are trimmed, at most 2000 characters; an empty one is stored as null.
- **Routes**: `POST` (201) and `GET /api/orgs/{org_id}/projects` create and list; `GET`, `PATCH` and `DELETE` (204) `/api/projects/{project_id}` address a project by its own id, without the organization in the path.
- **Shape**: `{id, organization_id, name, description, created_by, created_at, updated_at}`, `created_by` being a user id or null; listed oldest first. `PATCH` changes only the fields that are sent: `description: null` clears it, `name: null` is a 422. A project cannot move to another organization.
- **Access until US-011**: every member of the organization can create, see, change and delete its projects. Someone who is not a member gets 404 `Project not found`, the same body as for an id that does not exist (and 404 `Organization not found` on the two org-scoped routes).
- **`ProjectContextDep`** (`todolist.api.deps`) resolves `{project_id}` for the signed-in user and gives `ctx.project`, `ctx.membership`, `ctx.user` and `ctx.principal`. US-011 puts the permission service behind it.

## Project ACL and the permission service (2026-11-14, US-011)

- **Table**: `project_grants` with `project_id`, `principal_kind` (`user | agent`, PostgreSQL type `principal_kind`), `user_id`, `agent_id`, `role` (`viewer | editor | admin`, type `project_role`) and timestamps. A check constraint makes exactly the column that `principal_kind` names non-null; unique on `(project_id, user_id)` and on `(project_id, agent_id)`. Grants are deleted with their project, user or agent. The migration gives the creator of every existing project an admin grant.
- **Permission service**: `todolist.permissions`. `effective_project_role(session, principal, project)` (the story writes it without the session; a database lookup needs one) returns `admin` for owners and admins of the project's organization, otherwise the grant's role, otherwise `None`. `role_at_least(role, minimum)` compares roles (`viewer < editor < admin`); `visible_projects(principal)` is the same rule as a query, for lists.
- **A grant needs a membership**: a user's grant counts only while they are a member of the project's organization, and a principal acting in another organization has no role. Removing a member (or leaving) deletes their project grants in that organization, so joining again does not bring old access back.
- **An organization owner or admin is always admin**, also when a grant gives them a lower role.
- **Creating a project** is open to every member of the organization and gives the creator an admin grant. A plain member therefore sees their own projects and the ones shared with them, nothing else.
- **Routes**: `require_project_role(minimum)` in `todolist.api.deps` (aliases `ProjectContextDep` for viewer, `ProjectEditorContextDep`, `ProjectAdminContextDep`). No role → 404 `Project not found`; role too low → 403 `forbidden`. `GET` needs viewer, `PATCH` editor, `DELETE` admin. `ProjectContext` has `role` instead of `membership`.

## Project grants API (2026-11-14, US-012)

- **Routes**: `GET` and `PUT /api/projects/{project_id}/grants`, `DELETE /api/projects/{project_id}/grants/{grant_id}` (204). All three need the admin role on the project (`ProjectAdminContextDep`): 404 `Project not found` without a role, 403 for a viewer or editor.
- **Shape**: `{id, principal_kind, principal_id, name, email, role, created_at, updated_at}`, listed oldest first. `name` is the user's or the agent's current name; `email` is the user's and null for an agent (the sharing dialog needs it to tell people apart).
- **`PUT` is create-or-update** by `(principal_kind, principal_id)` and answers 200 in both cases, with the same grant id after an update. Roles are `viewer | editor | admin`; there is no `none` on a project (revoke the grant instead).
- **Who can get a grant**: a user who is a member of the project's organization or an agent that belongs to it. Anything else (another organization, an unknown id, a user id sent as an agent) answers 422 with code `invalid_principal`, without saying which of those it was.
- **Last admin** (409 `last_project_admin`): revoking or downgrading a user's admin grant is refused when afterwards no person could administer the project, that is when the organization has no owner or admin and no other member holds an admin grant. An agent's admin grant does not count: agents get their access from people. Because the API never leaves an organization without an owner (`last_owner`), this cannot happen through the API today; the rule guards the data against states reached another way (a deleted user). The only admin grant of a project can therefore normally be revoked, also by its holder: the organization's owners and admins remain.
- **Unknown grant id**, or a grant of another project → 404 `Grant not found`.
- **Rule placement**: `project_stays_administrable(session, project, without)` lives in `todolist.permissions`; `services/project_grants.py` (`list_project_grants`, `set_project_grant`, `revoke_project_grant`) applies it and raises the errors. The project row is locked during the check.

## Lists (2026-11-14, US-013)

- **Table**: `todo_lists` with `project_id` (cascade, indexed), `name` (200), `description` (text, nullable), `mode` (`human_only | ai_only | mixed`, PostgreSQL type `list_mode`), `position` (integer), `created_by` (the user; null when that user is deleted or when an agent created the list) and timestamps. Model `TodoList`, enum `ListMode`.
- **Names and descriptions** follow projects: trimmed, name 1 to 200 characters and not unique, description at most 2000 characters, an empty one stored as null.
- **Routes**: `POST` (201) and `GET /api/projects/{project_id}/lists` create and list; `GET`, `PATCH` and `DELETE` (204) `/api/lists/{list_id}` address a list by its own id.
- **Shape**: `{id, project_id, name, description, mode, position, created_by, created_at, updated_at}`. `PATCH` changes only the fields that are sent: `description: null` clears it, `name: null` and `mode: null` are a 422. A list cannot move to another project.
- **Default mode**: decided when the list is created (`mode` left out or null): `mixed` when the project's organization has at least one agent at that moment, otherwise `human_only`. Existing lists never change mode by themselves when agents are added or deleted.
- **Position**: a new list goes after the last one of its project (highest position + 1, starting at 1; the project row is locked while it is picked). The index is ordered by position, then age. Deleting a list leaves a gap; v1 has no story for reordering lists, so positions are ordered but not gap-free.
- **Access**: `effective_list_role(session, principal, todo_list, project)` in `todolist.permissions` is the one rule for a list; until US-014 it returns the role on the list's project. `require_list_role(minimum)` in `todolist.api.deps` (aliases `ListContextDep`, `ListEditorContextDep`, `ListAdminContextDep`) answers 404 `List not found` without a role and 403 `forbidden` when the role is too low. `GET` needs viewer, `POST` and `PATCH` editor, `DELETE` admin. The mode is stored but not enforced yet (US-017).
- **`create_list` takes a `Principal`**, so the MCP tools can share it.

## List ACL (2026-11-14, US-014)

- **Table**: `list_grants`, shaped like `project_grants` with `list_id` instead of `project_id` and `role` `none | viewer | editor | admin` (its own PostgreSQL type `list_role`; `principal_kind` is reused). Model `ListGrant`, enum `ListRole`. Grants are deleted with their list, user or agent.
- **Rule** (`effective_list_role(session, principal, todo_list, project)`): owners and admins of the organization are admin, whatever the grants say. For everyone else the list grant decides when there is one, also against a higher project role (`none` hides the list even from a project admin); without a list grant the project role applies. The result stays a `ProjectRole | None`: `none` and "no role at all" are the same answer (404).
- **A list grant needs a membership too**: it counts only while the user is a member of the organization (the agent belongs to it), and removing a member deletes their list grants in that organization along with their project grants.
- **List-only access**: a principal with a list grant and no project grant can use `/api/lists/{list_id}` according to that grant. The project stays closed to them: `GET /api/projects/{id}`, its grants and creating lists answer 404, and the project is not in the organization's project index. They learn the project's name from the list: the list shape gained `project_name`.
- **List index**: `GET /api/projects/{project_id}/lists` returns the lists the caller can see (`visible_lists(principal, project)` in `todolist.permissions`, the same rule as a query). It answers 404 `Project not found` only when the caller has no role on the project and sees none of its lists; a list-only principal gets just their lists, and someone with a project role whose lists are all hidden gets an empty list.
- **Grants API**: `GET` and `PUT /api/lists/{list_id}/grants`, `DELETE /api/lists/{list_id}/grants/{grant_id}` (204), all list admin (`ListAdminContextDep`), with the shape and answers of the project grants API (`PUT` is create-or-update, 422 `invalid_principal`, 404 `Grant not found`). `role` also takes `none`. `GET` returns the grants on the list itself, not the inherited project roles. Revoking a list grant brings the project role back.
- **No last-admin rule on lists**: the organization's owners and admins are always admin on every list, so a list cannot become unreachable. A list admin can lower or hide their own access.
- **Creating a list** still needs editor on the project; the creator gets no list grant (their project role covers it).

## Items (2026-11-14, US-015)

- **Table**: `items` with `list_id` (cascade), `title` (500), `notes` (text, nullable), `status` (`open | done`, PostgreSQL type `item_status`), `position` (integer), `created_by_kind` + `created_by_id`, `completed_by_kind` + `completed_by_id` (nullable), `completed_at` (nullable) and timestamps; index on `(list_id, position)`. Model `Item`, enum `ItemStatus`. The `*_kind` columns reuse `principal_kind`.
- **Actor columns have no foreign key**: the id points to a user or an agent depending on the kind, and it is a record of who did it. It stays when that user or agent is deleted (the audit log of US-018 keeps the name).
- **Completion matches status**: a check constraint makes `completed_by_kind`, `completed_by_id` and `completed_at` all set on a `done` item and all null on an `open` one. `completed_at` is the database's clock.
- **Completing a done item changes nothing**: it keeps its first completer and time. Only `open → done` records a completion and only `done → open` clears it.
- **Titles** are trimmed, 1 to 500 characters. **Notes** are trimmed, at most 10000 characters; empty notes are stored as null.
- **Routes**: `GET` (viewer) and `POST` (201, editor) `/api/lists/{list_id}/items`; `GET` (viewer), `PATCH` (editor) and `DELETE` (204, editor) `/api/items/{item_id}`. The role is the caller's effective role on the item's list. No role → 404 `List not found` / `Item not found`; too low → 403. `GET /api/items/{item_id}` is not in the story; it is there for symmetry with lists and projects.
- **Shape**: `{id, list_id, title, notes, status, position, created_by: {kind, id}, completed_by: {kind, id} | null, completed_at, created_at, updated_at}`. `PATCH` changes only the fields that are sent: `notes: null` clears them, `title: null` and `status: null` are a 422. Actor names are not in the shape yet; a story that shows them (the UI, the audit log) adds them.
- **Position**: a new item goes after the last one of its list (highest position + 1, starting at 1; the list row is locked while it is picked). Deleting leaves a gap until US-016 makes positions gap-free.
- **Service**: `services/items.py` (`list_items`, `create_item`, `update_item`, `delete_item`); the functions that change something take the acting `Principal`. Like the list service, they trust the caller to have checked the role. The list mode is not enforced yet (US-017).
